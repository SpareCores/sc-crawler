from json import dumps
from os.path import join

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import Enum as SaEnum
from sqlalchemy.dialects import postgresql, sqlite
from sqlmodel import Session, create_engine, select, update
from typer.testing import CliRunner

from sc_crawler import cli as cli_module
from sc_crawler.alembic_helpers import pkg_folder
from sc_crawler.archive_rules import archive_rules
from sc_crawler.cli import cli, supported_vendors
from sc_crawler.table_fields import Allocation, HashableDict, ResourceType, Status
from sc_crawler.tables import (
    ArchiveRule,
    Benchmark,
    BenchmarkScore,
    Region,
    Server,
    ServerPrice,
    Zone,
    tables,
)
from sc_crawler.tables_scd import tables_scd
from sc_crawler.utils import create_sc_engine, table_name_to_model

# child tables of the archived records, as listed in the RFC on archived records
CHILD_TABLES = {
    "vendor": {
        "vendor_compliance_link",
        "region",
        "zone",
        "storage",
        "server",
        "server_price",
        "server_description",
        "storage_price",
        "database",
        "database_price",
        "database_storage",
        "database_storage_price",
        "traffic_price",
        "ipv4_price",
        "benchmark_score",
    },
    "compliance_framework": {"vendor_compliance_link"},
    "region": {
        "zone",
        "server_price",
        "storage_price",
        "traffic_price",
        "ipv4_price",
        "database_price",
        "database_storage_price",
    },
    "zone": {"server_price"},
    "server": {"server_price", "server_description", "benchmark_score"},
    "storage": {"storage_price"},
    "database": {"database_price", "benchmark_score"},
    "database_storage": {"database_storage_price"},
    "benchmark": {"benchmark_score"},
}
# benchmark scores reference servers/databases by resource_type and resource_id
RESOURCE_PARENTS = {
    "server": ("server_id", ResourceType.SERVER),
    "database": ("database_id", ResourceType.DATABASE),
}

runner = CliRunner()


def _primary_keys(model) -> list[str]:
    return model.get_columns()["primary_keys"]


def _engine(path=None):
    engine = create_sc_engine(f"sqlite:///{path}" if path else "sqlite://")
    for table in tables:
        table.__table__.create(engine)
    return engine


def _region(region_id, status=Status.ACTIVE, vendor_id="hcloud"):
    return Region(
        vendor_id=vendor_id,
        region_id=region_id,
        name=region_id,
        api_reference=region_id,
        display_name=region_id,
        country_id="DE",
        status=status,
    )


def _zone(region_id, status=Status.ACTIVE):
    return Zone(
        vendor_id="hcloud",
        region_id=region_id,
        zone_id=region_id,
        name=region_id,
        api_reference=region_id,
        display_name=region_id,
        status=status,
    )


def _server_price(region_id, status=Status.ACTIVE, server_id="1"):
    return ServerPrice(
        vendor_id="hcloud",
        region_id=region_id,
        zone_id=region_id,
        server_id=server_id,
        allocation=Allocation.ONDEMAND,
        operating_system="Linux",
        unit="HOUR",
        price=1,
        price_upfront=0,
        price_tiered=[],
        currency="USD",
        status=status,
    )


def _benchmark(benchmark_id, status=Status.ACTIVE):
    return Benchmark(
        benchmark_id=benchmark_id,
        name=benchmark_id,
        framework="foo",
        status=status,
    )


def _score(benchmark_id, status=Status.ACTIVE, server_id="1"):
    return BenchmarkScore(
        vendor_id="hcloud",
        benchmark_id=benchmark_id,
        resource_type=ResourceType.SERVER,
        resource_id=server_id,
        config=HashableDict(a=2, b=1),
        score=42,
        status=status,
    )


def _statuses(session: Session, model) -> dict:
    """Statuses of the rows of a table by region or benchmark id."""
    key = "benchmark_id" if hasattr(model, "benchmark_id") else "region_id"
    return dict(session.exec(select(getattr(model, key), model.status)).all())


def _seed(session: Session, status=Status.INACTIVE):
    """Old and new Hetzner records and benchmarks, as before adding the rules."""
    session.add_all(
        [
            _region("2", status),
            _region("nbg1"),
            _zone("2", status),
            _zone("nbg1"),
            _server_price("2", status),
            _server_price("nbg1"),
            _benchmark("app:static_web", status),
            _benchmark("static_web:rps"),
            _score("app:static_web", status),
            _score("static_web:rps"),
        ]
    )
    session.commit()


# ##############################################################################
# rule definitions


def test_archive_rules_are_valid():
    assert ArchiveRule.check() == []


def test_archive_rules_have_sorted_keys():
    for rule in archive_rules:
        assert list(rule.match) == sorted(rule.match)
        assert list(rule.successor) == sorted(rule.successor)
    rule = ArchiveRule(
        table_name="benchmark_score",
        match={"config": {"b": 1, "a": 2}, "benchmark_id": "foo"},
    )
    assert dumps(rule.match) == '{"benchmark_id": "foo", "config": {"a": 2, "b": 1}}'
    assert rule.successor == {}
    validated = ArchiveRule.get_validator().model_validate(
        {"table_name": "zone", "match": {"zone_id": "1", "vendor_id": "foo"}}
    )
    assert list(validated.match) == ["vendor_id", "zone_id"]
    assert validated.successor == {}


def test_initial_archive_rules():
    rules = {(r.table_name, *r.match.values()): r.successor for r in archive_rules}
    for old, new in {
        "2": "nbg1",
        "3": "hel1",
        "4": "fsn1",
        "5": "ash",
        "6": "hil",
        "7": "sin",
    }.items():
        assert rules[("region", old, "hcloud")] == {
            "vendor_id": "hcloud",
            "region_id": new,
        }
        assert rules[("zone", old, "hcloud", old)] == {
            "vendor_id": "hcloud",
            "region_id": new,
            "zone_id": new,
        }
    assert rules[("benchmark", "app:static_web")] == {"benchmark_id": "static_web:rps"}


@pytest.mark.parametrize(
    "rules, problem",
    [
        ([dict(table_name="foo", match={"foo_id": "1"})], "unknown table"),
        ([dict(table_name="region_scd", match={"region_id": "1"})], "SCD"),
        ([dict(table_name="region", match={})], "empty match"),
        ([dict(table_name="region", match={"name": "foo"})], "not primary keys"),
        (
            [
                dict(
                    table_name="region",
                    match={"vendor_id": "foo", "region_id": "1"},
                    successor={"region_id": "2"},
                )
            ],
            "different keys",
        ),
        (
            [
                dict(
                    table_name="benchmark",
                    match={"benchmark_id": "foo"},
                    successor={"benchmark_id": "foo"},
                )
            ],
            "itself",
        ),
        ([dict(table_name="benchmark", match={"benchmark_id": "foo"})], "no reason"),
        (
            [
                dict(
                    table_name="benchmark",
                    match={"benchmark_id": old},
                    successor={"benchmark_id": new},
                )
                for old, new in [("a", "b"), ("b", "c"), ("c", "a")]
            ],
            "leads back",
        ),
        (
            # a -> b on all configs, then b -> a on a single config
            [
                dict(
                    table_name="benchmark_score",
                    match={"benchmark_id": "a"},
                    successor={"benchmark_id": "b"},
                ),
                dict(
                    table_name="benchmark_score",
                    match={"benchmark_id": "b", "config": {"x": 1}},
                    successor={"benchmark_id": "a", "config": {"x": 1}},
                ),
            ],
            "leads back",
        ),
    ],
)
def test_check_archive_rules_finds_problems(rules, problem):
    problems = ArchiveRule.check([ArchiveRule(**rule) for rule in rules])
    assert problems
    assert all(problem in p for p in problems)


def test_check_archive_rules_allows_chains_splits_merges_and_drops():
    rules = [
        # chain
        ("benchmark", {"benchmark_id": "a"}, {"benchmark_id": "b"}, None),
        ("benchmark", {"benchmark_id": "b"}, {"benchmark_id": "c"}, None),
        # split
        ("benchmark", {"benchmark_id": "d"}, {"benchmark_id": "e"}, None),
        ("benchmark", {"benchmark_id": "d"}, {"benchmark_id": "f"}, None),
        # merge
        ("benchmark", {"benchmark_id": "g"}, {"benchmark_id": "c"}, None),
        # dropped
        ("benchmark", {"benchmark_id": "h"}, {}, "Not needed anymore."),
        # renamed benchmark and re-keyed configs, independently
        ("benchmark_score", {"benchmark_id": "a"}, {"benchmark_id": "b"}, None),
        ("benchmark_score", {"config": {"x": 1}}, {"config": {"y": 1}}, None),
        # same ids in another table
        ("region", {"region_id": "b"}, {"region_id": "a"}, None),
    ]
    rules = [
        ArchiveRule(table_name=t, match=m, successor=s, reason=r)
        for t, m, s, r in rules
    ]
    assert ArchiveRule.check(rules) == []


# ##############################################################################
# matching against the schema


def test_parent_tables():
    for table in tables:
        table_name = table.get_table_name()
        children = {
            t.get_table_name() for t in tables if table_name in t.get_parent_tables()
        }
        assert children == CHILD_TABLES.get(table_name, set())


def test_child_tables_have_the_key_columns_of_their_parents():
    """Child records are matched by the key columns of the rules on their parents."""
    checked = 0
    for table in tables:
        pks = _primary_keys(table)
        for constraint in table.__table__.foreign_key_constraints:
            if not all(column.primary_key for column in constraint.columns):
                continue
            parent_pks = [c.name for c in constraint.referred_table.primary_key]
            assert set(parent_pks) <= set(pks), (table.get_table_name(), parent_pks)
            # and the foreign key uses the columns with the same name
            for element in constraint.elements:
                assert element.parent.name == element.column.name
            checked += 1
    assert checked > 20
    # servers and databases of benchmark scores are referenced without a
    # foreign key, as resource_id with the related resource_type
    score_pks = _primary_keys(BenchmarkScore)
    for parent, (id_column, _) in RESOURCE_PARENTS.items():
        parent_pks = _primary_keys(table_name_to_model(parent))
        assert set(parent_pks) - {id_column} <= set(score_pks)
        assert id_column in parent_pks
        assert id_column not in score_pks
    assert {"resource_type", "resource_id"} <= set(score_pks)


def test_tables_and_scd_tables_have_the_same_primary_keys():
    for table in tables:
        scd_pks = _primary_keys(table.get_scd())
        assert set(scd_pks) == set(_primary_keys(table)) | {"observed_at"}
    assert len(tables) == len(tables_scd)


def test_is_archived():
    def price(region_id, zone_id):
        return {
            "vendor_id": "hcloud",
            "region_id": region_id,
            "zone_id": zone_id,
            "server_id": "1",
            "allocation": "ondemand",
        }

    assert Region.is_archived({"vendor_id": "hcloud", "region_id": "2"})
    assert not Region.is_archived({"vendor_id": "hcloud", "region_id": "nbg1"})
    assert not Region.is_archived({"vendor_id": "aws", "region_id": "2"})
    assert ServerPrice.is_archived(price("2", "2"))
    assert not ServerPrice.is_archived(price("nbg1", "nbg1"))
    # not a child of the regions
    assert not Server.is_archived({"vendor_id": "hcloud", "server_id": "2"})
    score = {
        "vendor_id": "aws",
        "benchmark_id": "app:static_web",
        "resource_type": "server",
        "resource_id": "t3.nano",
        "config": {},
    }
    assert BenchmarkScore.is_archived(score)
    assert not BenchmarkScore.is_archived(score | {"benchmark_id": "foo"})


def test_rules_match_dict_columns_as_a_whole():
    rules = [
        ArchiveRule(
            table_name="benchmark_score",
            match={"benchmark_id": "foo", "config": {"b": 1, "a": 2}},
            reason="Re-keyed config.",
        )
    ]
    score = {
        "vendor_id": "aws",
        "benchmark_id": "foo",
        "resource_type": "server",
        "resource_id": "t3.nano",
    }
    assert BenchmarkScore.is_archived(score | {"config": {"a": 2, "b": 1}}, rules)
    assert not BenchmarkScore.is_archived(score | {"config": {"a": 2}}, rules)
    assert not BenchmarkScore.is_archived(
        score | {"config": {"a": 2, "b": 1, "c": 3}}, rules
    )

    engine = _engine()
    with Session(engine) as session:
        session.add_all(
            [_score("foo"), _score("bar"), _score("foo", server_id="2")],
        )
        other = _score("foo", server_id="3")
        other.config = HashableDict(a=2)
        session.add(other)
        session.commit()
        assert ArchiveRule.apply(session, rules) == {"benchmark_score": 2}
        archived = session.exec(
            select(BenchmarkScore.benchmark_id, BenchmarkScore.resource_id).where(
                BenchmarkScore.status == Status.ARCHIVED
            )
        ).all()
        assert sorted(archived) == [("foo", "1"), ("foo", "2")]


# ##############################################################################
# applying the rules


def test_apply_archive_rules():
    engine = _engine()
    with Session(engine) as session:
        _seed(session)
        archived = ArchiveRule.apply(session)
        session.commit()
        assert archived == {
            "region": 1,
            "zone": 1,
            "server_price": 1,
            "benchmark": 1,
            "benchmark_score": 1,
        }
        for model in (Region, Zone, ServerPrice):
            assert _statuses(session, model) == {
                "2": Status.ARCHIVED,
                "nbg1": Status.ACTIVE,
            }
        for model in (Benchmark, BenchmarkScore):
            assert _statuses(session, model) == {
                "app:static_web": Status.ARCHIVED,
                "static_web:rps": Status.ACTIVE,
            }
        # all rules are stored, also the ones without records in the database
        rules = session.exec(select(ArchiveRule)).all()
        assert len(rules) == len(archive_rules)
        assert all(rule.status == Status.ACTIVE for rule in rules)
        # nothing to do on the next run
        assert ArchiveRule.apply(session) == {}
        assert len(session.exec(select(ArchiveRule)).all()) == len(archive_rules)


def test_apply_archive_rules_on_active_records_and_without_parents():
    engine = _engine()
    with Session(engine) as session:
        # child records without their parents in the database
        session.add_all([_server_price("2"), _server_price("nbg1")])
        session.add_all([_score("app:static_web"), _score("static_web:rps")])
        session.commit()
        assert ArchiveRule.apply(session) == {
            "server_price": 1,
            "benchmark_score": 1,
        }
        assert _statuses(session, ServerPrice)["2"] == Status.ARCHIVED
        assert _statuses(session, ServerPrice)["nbg1"] == Status.ACTIVE


def test_apply_archive_rules_marks_scores_of_servers_only_by_resource_type():
    engine = _engine()
    rules = [
        ArchiveRule(
            table_name="server",
            match={"vendor_id": "hcloud", "server_id": "1"},
            successor={"vendor_id": "hcloud", "server_id": "2"},
        )
    ]
    with Session(engine) as session:
        database_score = _score("foo")
        database_score.resource_type = ResourceType.DATABASE
        session.add_all([_score("foo"), _score("foo", server_id="2"), database_score])
        session.add_all([_server_price("nbg1"), _server_price("nbg1", server_id="2")])
        session.commit()
        assert ArchiveRule.apply(session, rules) == {
            "server_price": 1,
            "benchmark_score": 1,
        }
        archived = session.exec(
            select(BenchmarkScore.resource_type, BenchmarkScore.resource_id).where(
                BenchmarkScore.status == Status.ARCHIVED
            )
        ).all()
        assert archived == [(ResourceType.SERVER, "1")]


# ##############################################################################
# tracing


def _example_value(model, column: str):
    column_type = model.__table__.columns[column].type
    if isinstance(column_type, SaEnum):
        return list(column_type.enum_class)[0]
    if column == "config":
        return {"foo": "bar"}
    return f"{column}-example"


def _example_key(table_name: str, **overrides) -> dict:
    model = table_name_to_model(table_name)
    return {
        column: overrides.get(column, _example_value(model, column))
        for column in _primary_keys(model)
    }


def _example_score_key(resource_type: ResourceType) -> dict:
    """Key of a score of the example server or database."""
    parent, id_column = next(
        (parent, id_column)
        for parent, (id_column, parent_type) in RESOURCE_PARENTS.items()
        if parent_type == resource_type
    )
    return _example_key(
        "benchmark_score",
        resource_type=resource_type,
        resource_id=_example_value(table_name_to_model(parent), id_column),
    )


def test_archived_by_returns_the_rules_of_the_table_and_its_parents():
    """One rule per table, using the same example ids in all tables."""
    table_names = [t.get_table_name() for t in tables if t is not ArchiveRule]
    engine = _engine()
    with Session(engine) as session:
        for table_name in table_names:
            keys = [_example_key(table_name)]
            if table_name == "benchmark_score":
                keys = [
                    _example_score_key(resource_type) for resource_type in ResourceType
                ]
            for key in keys:
                session.add(ArchiveRule(table_name=table_name, match=key))
        session.commit()

        for table_name in table_names:
            parents = {
                p for p, children in CHILD_TABLES.items() if table_name in children
            }
            for resource_type in ResourceType:
                key = _example_key(table_name)
                expected = {table_name} | parents
                if table_name == "benchmark_score":
                    # a score is the child of either a server or a database
                    key = _example_score_key(resource_type)
                    expected -= {
                        parent
                        for parent, (_, parent_type) in RESOURCE_PARENTS.items()
                        if parent_type != resource_type
                    }
                # other columns, e.g. observed_at of SCD records, are ignored
                rules = table_name_to_model(table_name).archived_by(
                    session, key | {"observed_at": "now"}
                )
                assert {rule.table_name for rule in rules} == expected, table_name

        # other records are not archived
        for table_name in table_names:
            key = {
                column: value if column == "config" else "other"
                for column, value in _example_key(table_name).items()
                if column.endswith("_id") or column == "config"
            }
            model = table_name_to_model(table_name)
            assert model.archived_by(session, _example_key(table_name, **key)) == []


def test_archived_by_child_of_several_parents_and_removed_rules():
    engine = _engine()
    key = {
        "vendor_id": "hcloud",
        "region_id": "2",
        "zone_id": "2",
        "server_id": "1",
        # name of the enum member, as stored in the database
        "allocation": "ONDEMAND",
    }
    with Session(engine) as session:
        assert ServerPrice.archived_by(session, key) == []
        ArchiveRule.apply(session)
        # rules removed from the code are kept as inactive
        session.exec(update(ArchiveRule).values(status=Status.INACTIVE))
        session.commit()
        rules = ServerPrice.archived_by(session, key)
        assert [(rule.table_name, rule.match["region_id"]) for rule in rules] == [
            ("region", "2"),
            ("zone", "2"),
        ]
        assert all(rule.status == Status.INACTIVE for rule in rules)
        assert rules[0].successor == {"vendor_id": "hcloud", "region_id": "nbg1"}
        assert ServerPrice.archived_by(session, key | {"region_id": "nbg1"}) == []

        with pytest.raises(ValueError, match="Missing primary key"):
            ServerPrice.archived_by(session, {"vendor_id": "hcloud"})
        with pytest.raises(ValueError, match="Unknown table"):
            table_name_to_model("foo")
        with pytest.raises(ValueError):
            ServerPrice.archived_by(session, key | {"allocation": "foo"})


def test_archived_by_command(tmp_path):
    db = tmp_path / "db.sqlite"
    with Session(_engine(db)) as session:
        ArchiveRule.apply(session)
        session.commit()
    args = ["archived-by", "--connection-string", f"sqlite:///{db}"]
    result = runner.invoke(
        cli,
        [
            *args,
            "zone_scd",
            '{"vendor_id": "hcloud", "region_id": "2", "zone_id": "2"}',
        ],
    )
    assert result.exit_code == 0, result.output
    assert "region" in result.output and "zone" in result.output
    assert "nbg1" in result.output
    assert "datacenters" in result.output

    result = runner.invoke(cli, [*args, "benchmark", '{"benchmark_id": "foo"}'])
    assert result.exit_code == 0
    assert "No archive rule found" in result.output

    assert runner.invoke(cli, [*args, "benchmark", "{}"]).exit_code != 0
    assert runner.invoke(cli, [*args, "benchmark", "foo"]).exit_code != 0


# ##############################################################################
# CLI commands


def test_copy_exclude_status(tmp_path):
    source = tmp_path / "source.sqlite"
    with Session(_engine(source)) as session:
        _seed(session)
        ArchiveRule.apply(session)
        session.add(_region("inactive", Status.INACTIVE))
        session.commit()

    target = tmp_path / "all.sqlite"
    args = ["copy", "--source", f"sqlite:///{source}"]
    result = runner.invoke(cli, [*args, "--target", f"sqlite:///{target}"])
    assert result.exit_code == 0, result.output
    with Session(create_engine(f"sqlite:///{target}")) as session:
        assert _statuses(session, Region) == {
            "2": Status.ARCHIVED,
            "nbg1": Status.ACTIVE,
            "inactive": Status.INACTIVE,
        }

    target = tmp_path / "filtered.sqlite"
    result = runner.invoke(
        cli,
        [*args, "--target", f"sqlite:///{target}", "--exclude-status", "archived"],
    )
    assert result.exit_code == 0, result.output
    with Session(create_engine(f"sqlite:///{target}")) as session:
        assert _statuses(session, Region) == {
            "nbg1": Status.ACTIVE,
            "inactive": Status.INACTIVE,
        }
        for model in (Zone, ServerPrice):
            assert _statuses(session, model) == {"nbg1": Status.ACTIVE}
        assert _statuses(session, Benchmark) == {"static_web:rps": Status.ACTIVE}
        assert _statuses(session, BenchmarkScore) == {"static_web:rps": Status.ACTIVE}
        assert len(session.exec(select(ArchiveRule)).all()) == len(archive_rules)

    target = tmp_path / "active.sqlite"
    result = runner.invoke(
        cli,
        [
            *args,
            *["--target", f"sqlite:///{target}"],
            *["--exclude-status", "archived", "--exclude-status", "INACTIVE"],
        ],
    )
    assert result.exit_code == 0, result.output
    with Session(create_engine(f"sqlite:///{target}")) as session:
        assert _statuses(session, Region) == {"nbg1": Status.ACTIVE}


def test_copy_exclude_status_leaves_out_rows_referencing_left_out_rows(tmp_path):
    source = tmp_path / "source.sqlite"
    with Session(_engine(source)) as session:
        session.add_all(
            [
                _region("old", Status.INACTIVE),
                _zone("old"),
                _server_price("old"),
                _benchmark("old", Status.INACTIVE),
                _score("old"),
                _region("nbg1"),
                _zone("nbg1"),
                _server_price("nbg1"),
                _benchmark("static_web:rps"),
                _score("static_web:rps"),
            ]
        )
        session.commit()

    target = tmp_path / "active.sqlite"
    result = runner.invoke(
        cli,
        [
            *["copy", "--source", f"sqlite:///{source}"],
            *["--target", f"sqlite:///{target}", "--exclude-status", "inactive"],
        ],
    )
    assert result.exit_code == 0, result.output
    with Session(create_engine(f"sqlite:///{target}")) as session:
        for model in (Region, Zone, ServerPrice):
            assert _statuses(session, model) == {"nbg1": Status.ACTIVE}
        for model in (Benchmark, BenchmarkScore):
            assert _statuses(session, model) == {"static_web:rps": Status.ACTIVE}


def test_downgrade_resets_archived_statuses(tmp_path):
    connection_string = f"sqlite:///{tmp_path / 'db.sqlite'}"
    upgrade = ["schemas", "upgrade", "--connection-string", connection_string]
    assert runner.invoke(cli, upgrade).exit_code == 0
    with Session(create_sc_engine(connection_string)) as session:
        session.add(_region("2", Status.ARCHIVED))
        session.commit()

    result = runner.invoke(
        cli,
        [
            *["schemas", "downgrade", "--connection-string", connection_string],
            *["--revision", "7e3a9c1b5d24"],
        ],
    )
    assert result.exit_code == 0, result.output
    with create_engine(connection_string).connect() as conn:
        assert conn.exec_driver_sql("SELECT status FROM region").all() == [
            ("INACTIVE",)
        ]


def test_sync_handles_rows_found_only_in_target(tmp_path):
    source = tmp_path / "source.sqlite"
    target = tmp_path / "target.sqlite"
    log = tmp_path / "changes.log"
    with Session(_engine(source)) as session:
        session.add_all([_region("nbg1"), _zone("nbg1"), _benchmark("static_web:rps")])
        ArchiveRule.apply(session)
        session.commit()
    with Session(_engine(target)) as session:
        session.add_all(
            [
                _region("nbg1"),
                _zone("nbg1"),
                _benchmark("static_web:rps"),
                # already archived
                _region("2", Status.ARCHIVED),
                # matching a rule or the child of such a record
                _region("3", Status.INACTIVE),
                _zone("3", Status.ACTIVE),
                _server_price("4", Status.INACTIVE),
                # no rule
                _region("gone", Status.ACTIVE),
                _region("gone-earlier", Status.INACTIVE),
                # archived by hand without a rule: kept as-is
                _region("manual", Status.ARCHIVED),
            ]
        )
        session.commit()
        observed_at = dict(
            session.exec(select(Region.region_id, Region.observed_at)).all()
        )

    result = runner.invoke(
        cli,
        [
            "sync",
            *["--source", f"sqlite:///{source}", "--target", f"sqlite:///{target}"],
            *["--log-changes-path", str(log)],
        ],
    )
    assert result.exit_code == 0, result.output

    with Session(create_engine(f"sqlite:///{target}")) as session:
        assert _statuses(session, Region) == {
            "nbg1": Status.ACTIVE,
            "2": Status.ARCHIVED,
            "3": Status.ARCHIVED,
            "gone": Status.INACTIVE,
            "gone-earlier": Status.INACTIVE,
            "manual": Status.ARCHIVED,
        }
        assert _statuses(session, Zone) == {
            "nbg1": Status.ACTIVE,
            "3": Status.ARCHIVED,
        }
        assert _statuses(session, ServerPrice) == {"4": Status.ARCHIVED}
        # only the changed rows are written
        new_observed_at = dict(
            session.exec(select(Region.region_id, Region.observed_at)).all()
        )
        changed = {k for k, v in new_observed_at.items() if v != observed_at[k]}
        assert changed == {"3", "gone"}
        # the rules are synced like the other tables
        rules = session.exec(select(ArchiveRule)).all()
        assert len(rules) == len(archive_rules)

    changes = log.read_text()
    assert "- Deleted: hcloud/3\n" in changes
    assert "- Deleted: hcloud/gone\n" in changes
    assert "hcloud/2\n" not in changes
    assert '- New: region/{"region_id": "2", "vendor_id": "hcloud"}/' in changes

    # nothing to sync on the second run
    result = runner.invoke(
        cli,
        ["sync", "--source", f"sqlite:///{source}", "--target", f"sqlite:///{target}"],
    )
    assert result.exit_code == 0, result.output
    with Session(create_engine(f"sqlite:///{target}")) as session:
        assert new_observed_at == dict(
            session.exec(select(Region.region_id, Region.observed_at)).all()
        )


def test_sync_applies_the_rules_to_the_synced_tables_only(tmp_path):
    source = tmp_path / "source.sqlite"
    target = tmp_path / "target.sqlite"
    _engine(source)
    with Session(_engine(target)) as session:
        session.add_all([_region("2"), _zone("2"), _server_price("2")])
        session.commit()
    result = runner.invoke(
        cli,
        [
            "sync",
            *["--source", f"sqlite:///{source}", "--target", f"sqlite:///{target}"],
            *["--sync-tables", "server_price"],
        ],
    )
    assert result.exit_code == 0, result.output
    with Session(create_engine(f"sqlite:///{target}")) as session:
        assert _statuses(session, ServerPrice) == {"2": Status.ARCHIVED}
        assert _statuses(session, Region) == {"2": Status.ACTIVE}
        assert _statuses(session, Zone) == {"2": Status.ACTIVE}


def test_unmatched_archive_rules():
    source, target = _engine(), _engine()
    with Session(source) as source_session, Session(target) as target_session:
        # all the archived records are only in the target
        _seed(target_session, Status.ARCHIVED)
        sessions = [source_session, target_session]
        messages = ArchiveRule.find_unmatched(sessions, ["region", "benchmark"])
        # regions 3-7 and their successors are in neither database
        assert len(messages) == 10
        assert all(m.startswith("Archive rule region ") for m in messages)
        assert not any("'region_id': '2'" in m or "nbg1" in m for m in messages)
        assert sum(m.endswith("for its match.") for m in messages) == 5
        assert sum(m.endswith("for its successor.") for m in messages) == 5

        assert ArchiveRule.find_unmatched(sessions, ["server"]) == []
        assert len(ArchiveRule.find_unmatched(sessions)) == 20
        assert len(ArchiveRule.find_unmatched([source_session])) == 26

        rules = [
            ArchiveRule(
                table_name="benchmark",
                match={"benchmark_id": "app:static_web"},
                reason="Dropped.",
            ),
            ArchiveRule(
                table_name="benchmark_score",
                match={"benchmark_id": "typo"},
                successor={"benchmark_id": "static_web:rps"},
            ),
        ]
        messages = ArchiveRule.find_unmatched(sessions, rules=rules)
        assert len(messages) == 1
        assert messages[0].startswith(
            "Archive rule benchmark_score {'benchmark_id': 'typo'}"
        )
        assert messages[0].endswith("for its match.")


def test_sync_reports_unmatched_archive_rules(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite"
    target = tmp_path / "target.sqlite"
    with Session(_engine(source)) as session:
        _seed(session)
    _engine(target)
    warnings = []
    monkeypatch.setattr(cli_module.logger, "warning", warnings.append)
    result = runner.invoke(
        cli,
        [
            "sync",
            *["--source", f"sqlite:///{source}", "--target", f"sqlite:///{target}"],
            *["--sync-tables", "region", "--sync-tables", "benchmark"],
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    # regions 3-7 and their successors, but not the rules of other tables
    assert len(warnings) == 10
    assert all(w.startswith("Archive rule region ") for w in warnings)


def test_dict_primary_keys_are_comparable_in_postgresql():
    """JSON has no equality operator in PostgreSQL, unlike JSONB."""
    for column in (BenchmarkScore.config, ArchiveRule.match, ArchiveRule.successor):
        condition = column == {"foo": "bar"}
        assert "::JSONB" in str(condition.compile(dialect=postgresql.dialect()))
        assert "JSONB" not in str(condition.compile(dialect=sqlite.dialect()))


def test_migrations_have_a_single_head():
    assert len(ScriptDirectory(join(pkg_folder, "alembic")).get_heads()) == 1


def test_pull_applies_the_archive_rules_as_last_step(tmp_path):
    connection_string = f"sqlite:///{tmp_path / 'db.sqlite'}"
    result = runner.invoke(
        cli, ["schemas", "upgrade", "--connection-string", connection_string]
    )
    assert result.exit_code == 0, result.output
    with Session(create_sc_engine(connection_string)) as session:
        # migrations do not add rules or set statuses
        assert session.exec(select(ArchiveRule)).all() == []
        _seed(session)
        session.add(
            ArchiveRule(
                table_name="benchmark",
                match={"benchmark_id": "removed-rule"},
                reason="Rule removed from the code.",
            )
        )
        session.commit()

    args = ["pull", "--connection-string", connection_string]
    for vendor in supported_vendors:
        args += ["--exclude-vendor", vendor.vendor_id]
    result = runner.invoke(cli, [*args, "--include-records", "regions"])
    assert result.exit_code == 0, result.output

    with Session(create_sc_engine(connection_string)) as session:
        for model in (Region, Zone, ServerPrice):
            assert _statuses(session, model) == {
                "2": Status.ARCHIVED,
                "nbg1": Status.ACTIVE,
            }
        statuses = _statuses(session, Benchmark)
        assert statuses["app:static_web"] == Status.ARCHIVED
        assert statuses["static_web:rps"] == Status.ACTIVE
        assert _statuses(session, BenchmarkScore) == {
            "app:static_web": Status.ARCHIVED,
            "static_web:rps": Status.ACTIVE,
        }
        rules = session.exec(select(ArchiveRule)).all()
        assert len(rules) == len(archive_rules) + 1
        assert [r.match for r in rules if r.status == Status.INACTIVE] == [
            {"benchmark_id": "removed-rule"}
        ]
