"""Helpers to match, apply, trace and check the [archive rules][sc_crawler.archive_rules].

[key_filters][sc_crawler.archive_helpers.key_filters] is the only place
defining which records a rule refers to: the SQL conditions used by `pull`
and `sync`, and the matching of primary keys in Python (e.g. for tracing)
are both built on that.
"""

from functools import cache
from typing import Dict, List, Optional, Set

from sqlalchemy import ColumnElement, and_, literal, or_, update
from sqlalchemy import Enum as SaEnum
from sqlmodel import Session, select

from .archive_rules import archive_rules
from .insert import insert_items
from .table_bases import ScModel
from .table_fields import ResourceType, Status
from .tables import ArchiveRule, tables

# Benchmark scores reference servers and databases without a foreign key:
# parent table -> (its id column, the related resource_type of the scores).
_BENCHMARK_SCORE_RESOURCES = {
    "server": ("server_id", ResourceType.SERVER),
    "database": ("database_id", ResourceType.DATABASE),
}


def _model(table_name: str) -> ScModel:
    """Look up the (non-SCD) table model of a table or its SCD twin."""
    name = table_name.removesuffix("_scd")
    for table in tables:
        if table.get_table_name() == name:
            return table
    raise ValueError(f"Unknown table: {table_name}")


@cache
def parent_tables(table_name: str) -> Set[str]:
    """Names of the tables whose archived records archive the records of a table.

    These are the tables referenced by a foreign key that is part of the
    primary key of the table, plus the servers and databases of benchmark
    scores, and the parents of all these tables.

    Examples:
        >>> sorted(parent_tables("zone"))
        ['region', 'vendor']
        >>> sorted(parent_tables("benchmark_score"))
        ['benchmark', 'database', 'server', 'vendor']
        >>> parent_tables("country")
        set()
    """
    parents = {
        constraint.referred_table.name
        for constraint in _model(table_name).__table__.foreign_key_constraints
        if all(column.primary_key for column in constraint.columns)
    }
    if table_name == "benchmark_score":
        parents.update(_BENCHMARK_SCORE_RESOURCES)
    for parent in list(parents):
        parents |= parent_tables(parent)
    return parents


def child_tables(table_name: str) -> List[str]:
    """Names of the tables with child records of the records of a table.

    Examples:
        >>> child_tables("zone")
        ['server_price']
        >>> child_tables("benchmark")
        ['benchmark_score']
    """
    names = [table.get_table_name() for table in tables]
    return [name for name in names if table_name in parent_tables(name)]


def key_filters(rule_table_name: str, keys: dict, table_name: str) -> Optional[dict]:
    """Translate the `match` or `successor` of a rule into column filters on a table.

    This is the only place defining which records a rule refers to, used both
    for the SQL conditions and for matching primary keys in Python.

    Args:
        rule_table_name: The `table_name` of the rule.
        keys: The `match` or `successor` of the rule.
        table_name: Table to be filtered, which is the table of the rule, or
            a table with its child records.

    Returns:
        Dict of column names and values of `table_name`, or `None` if the
            rule does not apply to the table.

    Examples:
        >>> key_filters("region", {"vendor_id": "hcloud", "region_id": "2"}, "server_price")
        {'vendor_id': 'hcloud', 'region_id': '2'}
        >>> key_filters("server", {"vendor_id": "aws", "server_id": "foo"}, "benchmark_score")
        {'vendor_id': 'aws', 'resource_type': <ResourceType.SERVER: 'server'>, 'resource_id': 'foo'}
        >>> key_filters("zone", {"vendor_id": "hcloud", "zone_id": "2"}, "region") is None
        True
    """
    table_name = table_name.removesuffix("_scd")
    if table_name != rule_table_name and rule_table_name not in parent_tables(
        table_name
    ):
        return None
    filters = dict(keys)
    if (
        table_name == "benchmark_score"
        and rule_table_name in _BENCHMARK_SCORE_RESOURCES
    ):
        id_column, resource_type = _BENCHMARK_SCORE_RESOURCES[rule_table_name]
        filters["resource_type"] = resource_type
        if id_column in filters:
            filters["resource_id"] = filters.pop(id_column)
    return filters


def rule_matches(rule: ArchiveRule, table_name: str, primary_key: dict) -> bool:
    """Check if a rule archives the record of a table with the given primary key.

    Examples:
        >>> rule = ArchiveRule(table_name="benchmark", match={"benchmark_id": "foo"})
        >>> rule_matches(rule, "benchmark", {"benchmark_id": "foo"})
        True
        >>> rule_matches(rule, "benchmark_score", {"vendor_id": "aws", "benchmark_id": "foo", "resource_type": "server", "resource_id": "bar", "config": {}})
        True
        >>> rule_matches(rule, "benchmark", {"benchmark_id": "bar"})
        False
    """  # noqa: E501
    filters = key_filters(rule.table_name, rule.match, table_name)
    if filters is None:
        return False
    return all(
        column in primary_key and primary_key[column] == value
        for column, value in filters.items()
    )


def is_archived(
    table_name: str, primary_key: dict, rules: Optional[List[ArchiveRule]] = None
) -> bool:
    """Check if any of the rules (default: all current rules) archives a record."""
    if rules is None:
        rules = archive_rules
    return any(rule_matches(rule, table_name, primary_key) for rule in rules)


def _filters_condition(model: ScModel, filters: dict) -> ColumnElement:
    """SQL condition selecting the rows of a table with the given column values."""
    return and_(*[getattr(model, column) == value for column, value in filters.items()])


def archive_condition(
    model: ScModel, rules: Optional[List[ArchiveRule]] = None
) -> Optional[ColumnElement]:
    """SQL condition selecting the rows of a table archived by the rules.

    Child records are selected by the key columns of the rules instead of
    looking up their parents, so it also finds the child records of parents
    that are not in the database.

    Args:
        model: Table to be filtered.
        rules: Rules to apply. Defaults to all current rules.

    Returns:
        SQLAlchemy condition, or `None` if no rule applies to the table.
    """
    if rules is None:
        rules = archive_rules
    table_name = model.get_table_name()
    conditions = []
    for rule in rules:
        filters = key_filters(rule.table_name, rule.match, table_name)
        if filters is not None:
            conditions.append(_filters_condition(model, filters))
    return or_(*conditions) if conditions else None


def apply_archive_rules(
    session: Session, rules: Optional[List[ArchiveRule]] = None
) -> Dict[str, int]:
    """Store the rules in the database, and archive the records they match.

    All rules are written to the `archive_rule` table (also the ones not
    matching any record), then the matched records and their child records
    are set to [ARCHIVED][sc_crawler.table_fields.Status].

    Args:
        session: Database connection. Changes are not committed.
        rules: Rules to apply. Defaults to all current rules.

    Returns:
        Number of newly archived records per table name.
    """
    if rules is None:
        rules = archive_rules
    items = [rule.model_dump(exclude={"observed_at"}) for rule in rules]
    insert_items(ArchiveRule, items, session=session)
    archived = {}
    for model in tables:
        condition = archive_condition(model, rules)
        if condition is None:
            continue
        result = session.exec(
            update(model)
            .where(condition)
            .where(model.status != Status.ARCHIVED)
            .values(status=Status.ARCHIVED)
        )
        if result.rowcount:
            archived[model.get_table_name()] = result.rowcount
    return archived


def _coerce_key_value(model: ScModel, column: str, value):
    """Convert the name or value of an enum member to the member for enum columns."""
    column_type = model.__table__.columns[column].type
    if isinstance(column_type, SaEnum) and column_type.enum_class is not None:
        enum_class = column_type.enum_class
        if isinstance(value, str) and value in enum_class.__members__:
            return enum_class[value]
        return enum_class(value)
    return value


def archived_by(
    session: Session, table_name: str, primary_key: dict
) -> List[ArchiveRule]:
    """List the rules archiving a record, including the rules on its parent tables.

    Reads the rules from the `archive_rule` table of the database, so it also
    returns the rules that were removed from the code since (stored with
    `INACTIVE` status), and uses the same matching as `pull` and `sync`.
    It does not look up the record itself.

    Args:
        session: Database connection.
        table_name: Name of the table of the record, or of its SCD twin.
        primary_key: All primary key columns of the record with their values.
            Other keys (e.g. `observed_at` of an SCD record) are ignored.

    Returns:
        The matching rules, ordered by table name, `match` and `successor`.

    Examples:
        >>> archived_by(session, "server_price", {"vendor_id": "hcloud", "region_id": "2", "zone_id": "2", "server_id": "1", "allocation": "ondemand"})  # doctest: +SKIP
        [ArchiveRule(table_name='region', ...), ArchiveRule(table_name='zone', ...)]
    """  # noqa: E501
    model = _model(table_name)
    columns = model.get_columns()["primary_keys"]
    missing = [column for column in columns if column not in primary_key]
    if missing:
        raise ValueError(
            f"Missing primary key column(s) of {table_name}: {', '.join(missing)}"
        )
    key = {
        column: _coerce_key_value(model, column, primary_key[column])
        for column in columns
    }
    rules = session.exec(select(ArchiveRule)).all()
    rules = [rule for rule in rules if rule_matches(rule, table_name, key)]
    return sorted(
        rules,
        key=lambda rule: (rule.table_name, str(rule.match), str(rule.successor)),
    )


def unmatched_archive_rules(
    sessions: List[Session],
    table_names: Optional[List[str]] = None,
    rules: Optional[List[ArchiveRule]] = None,
) -> List[str]:
    """Describe the rules referring to records that are in none of the databases.

    Checks both the `match` and the (non-empty) `successor` of the rules,
    e.g. to find typos in the ids, or successors not provided by the vendor.

    Args:
        sessions: Connections to the databases to look up the records in.
        table_names: Check only the rules of these tables. Defaults to all tables.
        rules: Rules to check. Defaults to all current rules.

    Returns:
        A message for each `match` or `successor` without any record.
    """
    if rules is None:
        rules = archive_rules
    messages = []
    for rule in rules:
        if table_names is not None and rule.table_name not in table_names:
            continue
        model = _model(rule.table_name)
        for field in ("match", "successor"):
            keys = getattr(rule, field)
            if not keys:
                continue
            query = (
                select(literal(1))
                .select_from(model)
                .where(_filters_condition(model, keys))
                .limit(1)
            )
            if not any(session.exec(query).first() for session in sessions):
                messages.append(
                    f"Archive rule {rule.table_name} {dict(rule.match)} -> "
                    f"{dict(rule.successor)}: no record found for its {field}."
                )
    return messages


def check_archive_rules(rules: Optional[List[ArchiveRule]] = None) -> List[str]:
    """Check the definition of the rules, without a database.

    Args:
        rules: Rules to check. Defaults to all current rules.

    Returns:
        Description of the problems found: unknown tables, `match` keys that
            are not primary key columns of the table, `successor` with other
            keys than `match`, missing `reason` of rules without a successor,
            and rules leading back to a record they archived (cycles).
    """
    if rules is None:
        rules = archive_rules
    problems = []
    valid = []
    for rule in rules:
        label = f"{rule.table_name} {dict(rule.match)} -> {dict(rule.successor)}"
        try:
            primary_keys = _model(rule.table_name).get_columns()["primary_keys"]
        except ValueError:
            problems.append(f"{label}: unknown table")
            continue
        if rule.table_name.endswith("_scd"):
            problems.append(f"{label}: rules cannot refer to SCD tables")
            continue
        if not rule.match:
            problems.append(f"{label}: empty match")
            continue
        unknown = [key for key in rule.match if key not in primary_keys]
        if unknown:
            problems.append(f"{label}: match keys {unknown} are not primary keys")
            continue
        if rule.successor and set(rule.successor) != set(rule.match):
            problems.append(f"{label}: successor and match have different keys")
            continue
        if rule.successor == rule.match:
            problems.append(f"{label}: the successor is the archived record itself")
            continue
        if not rule.successor and not rule.reason:
            problems.append(f"{label}: no reason given for a rule without successor")
        valid.append(rule)

    def leads_back(start: ArchiveRule, known: dict, path: tuple) -> bool:
        """Follow the rules from the successor of `start`, with `known` key columns."""
        if all(known.get(k, start) == v for k, v in start.match.items()):
            return True
        return any(
            leads_back(start, {**known, **rule.match, **rule.successor}, path + (i,))
            for i, rule in enumerate(valid)
            if i not in path
            and rule.successor
            and rule.table_name == start.table_name
            # `known` holds the key columns set by the rules followed so far,
            # the other columns can have any value
            and all(known.get(k, v) == v for k, v in rule.match.items())
        )

    for i, rule in enumerate(valid):
        if rule.successor and leads_back(rule, dict(rule.successor), (i,)):
            problems.append(
                f"{rule.table_name} {dict(rule.match)} -> {dict(rule.successor)}: "
                "following the rules leads back to the archived record"
            )
    return problems
