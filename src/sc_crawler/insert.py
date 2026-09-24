from collections import defaultdict
from json import dumps
from logging import DEBUG
from typing import TYPE_CHECKING, List, Optional

from pydantic import BaseModel
from rich.progress import Progress
from sqlalchemy import tuple_, update
from sqlalchemy.dialects.postgresql import insert as insert_postgresql
from sqlalchemy.dialects.sqlite import insert as insert_sqlite
from sqlmodel import Session, SQLModel

from .str_utils import space_after
from .utils import chunk_list, is_postgresql, is_sqlite

# session.info: table name -> {primary-key JSON: content hash}, ignoring observed_at.
# Filled before a pull marks rows inactive, then reused so unchanged rows are not rewritten.
ROW_CONTENT_HASHES = "row_content_hashes"
# session.info: table names whose rows were just marked inactive.
# Unchanged rows in these tables are set back to the incoming status without touching observed_at.
INACTIVE_CONTENT_FLIPS = "row_content_hash_inactive_flips"

if TYPE_CHECKING:
    from .tables import Vendor


def can_bulk_insert(session: Session) -> bool:
    """Checks if bulk insert is supported for the engine dialect of a SQLModel session."""
    return is_sqlite(session) or is_postgresql(session)


def _primary_key_tuple(item: dict, primary_keys: list[str]) -> tuple[str, ...]:
    """Build a stable hashable key for deduplicating rows by primary key."""
    parts: list[str] = []
    for pk in primary_keys:
        value = item.get(pk)
        if isinstance(value, dict):
            parts.append(dumps(value, sort_keys=True))
        else:
            parts.append(str(value))
    return tuple(parts)


def _dedupe_items(
    items: List[dict],
    primary_keys: list[str],
    vendor: Optional["Vendor"] = None,
    model_name: str = "",
    prefix: str = "",
) -> List[dict]:
    """Deduplicate items by primary key, keeping the last occurrence."""
    seen = defaultdict(list)
    item_keys = []
    for item in items:
        key = _primary_key_tuple(item, primary_keys)
        item_keys.append(key)
        seen[key].append(item)

    duplicates_found = False
    for occurrences in seen.values():
        if len(occurrences) > 1:
            if not duplicates_found:
                if vendor:
                    duplicates_count = sum(
                        len(v) - 1 for v in seen.values() if len(v) > 1
                    )
                    vendor.log(
                        f"Found {duplicates_count} duplicate(s) in {space_after(prefix)}{model_name} items",
                    )
                duplicates_found = True

    unique_items = []
    seen_keys = set()
    for key, item in reversed(list(zip(item_keys, items))):
        if key not in seen_keys:
            seen_keys.add(key)
            unique_items.append(item)

    unique_items.reverse()
    return unique_items


def validate_items(
    model: BaseModel,
    items: List[dict],
    vendor: Optional["Vendor"] = None,
    prefix: str = "",
) -> List[dict]:
    """Validates a list of items against a [pydantic.BaseModel][] definition.

    Args:
        model: An SQLModel model to be used for validation.
        items: List of dictionaries to be checked against `model`.
        vendor: Optional Vendor instance used for logging and progress bar updates.
        prefix: Optional extra description for the model added in front of
            the model name in logs and progress bar updates.

    Returns:
        List of validated dicts in the same order. Note that missing fields
            has been filled in with default values (needed for bulk inserts).
    """
    model_name = model.get_table_name()
    # use the Pydantic data model for validation instead of the table definition
    schema = model.__validator__
    if vendor:
        vendor.progress_tracker.start_task(
            name=f"Validating {space_after(prefix)}{model_name}(s)", total=len(items)
        )
    for i, item in enumerate(items):
        items[i] = schema.model_validate(item).model_dump()
        if vendor:
            vendor.progress_tracker.advance_task()
    if vendor:
        vendor.progress_tracker.hide_task()
        vendor.log(
            "%d %s%s(s) objects validated"
            % (len(items), space_after(prefix), model_name),
            DEBUG,
        )
    return items


def bulk_insert_items(
    model: SQLModel,
    items: List[dict],
    vendor: Optional["Vendor"] = None,
    session: Optional[Session] = None,
    progress: Optional[Progress] = None,
    prefix: str = "",
):
    """Bulk inserts items into a SQLModel table with `ON CONFLICT` update.

    Args:
        model: An SQLModel table definition with primary key(s).
        items: List of dicts with all columns of the model.
        vendor: Optional related Vendor instance used for logging and progress bar updates.
        session: Optional database connections. When not provided, defaults to the `vendor`'s session.
        progress: Optional progress bar to use instead of `vendor`'s progress bar.
        prefix: Optional extra description for the model added in front of
            the model name in logs and progress bar updates.
    """
    if session is None:
        if vendor is None:
            raise TypeError("At least one of `session` or `vendor` is required.")
        session = vendor.session
    model_name = model.get_table_name()
    columns = model.get_columns()
    if progress:
        pid = progress.add_task(
            f"Inserting {space_after(prefix)}{model_name}(s)", total=len(items)
        )
    elif vendor:
        pid = vendor.progress_tracker.start_task(
            name=f"Inserting {space_after(prefix)}{model_name}(s)", total=len(items)
        )
        progress = vendor.progress_tracker.tasks
    # need to split list into smaller chunks to avoid "too many SQL variables"
    for chunk in chunk_list(items, 100):
        if is_sqlite(session):
            query = insert_sqlite(model).values(chunk)
            query = query.on_conflict_do_update(
                index_elements=[getattr(model, c) for c in columns["primary_keys"]],
                set_={c: query.excluded[c] for c in columns["attributes"]},
            )
        elif is_postgresql(session):
            query = insert_postgresql(model).values(chunk)
            query = query.on_conflict_do_update(
                constraint=model.__table__.primary_key,
                set_={c: query.excluded[c] for c in columns["attributes"]},
            )
        else:
            raise NotImplementedError(
                "Unsupported database engine dialect for bulk inserts."
            )
        session.exec(query)
        if progress:
            progress.update(pid, advance=len(chunk))

    if vendor:
        vendor.progress_tracker.hide_task()
        vendor.log(f"{len(items)} {space_after(prefix)}{model_name}(s) synced.")


def insert_items(
    model: SQLModel,
    items: List[dict],
    vendor: Optional["Vendor"] = None,
    session: Optional[Session] = None,
    progress: Optional[Progress] = None,
    prefix: str = "",
):
    """Insert items into the related database table using bulk or merge.

    Bulk insert is only supported with SQLite, other databases fall back to
    the default session.merge (slower) approach.

    Args:
        model: An SQLModel table definition with primary key(s).
        items: List of dicts with all columns of the model.
        vendor: Optional related Vendor instance used for database connection, logging and progress bar updates.
        session: Optional database connections. When not provided, defaults to the `vendor`'s session.
        progress: Optional progress bar to use instead of `vendor`'s progress bar.
        prefix: Optional extra description for the model added in front of
            the model name in logs and progress bar updates.
    """
    if session is None:
        if vendor is None:
            raise TypeError("At least one of `session` or `vendor` is required.")
        session = vendor.session
    model_name = model.get_table_name()
    columns = model.get_columns()
    primary_keys = columns["primary_keys"]

    # Validate first so JSON primary-key columns (e.g. BenchmarkScore.config)
    # are canonicalized before deduplication.
    items = validate_items(model, items, vendor, prefix)
    items = _dedupe_items(items, primary_keys, vendor, model_name, prefix)

    cache = session.info.setdefault(ROW_CONTENT_HASHES, {})
    table_name = model.get_table_name()
    hashes = cache.get(table_name)
    if hashes is None:
        hashes = model.hash(session)
        cache[table_name] = hashes
    incoming_hashes = model.hash(session, rows=items)
    pks = sorted(primary_keys)
    changed = []
    unchanged = []
    for item in items:
        keys_id = dumps({pk: item.get(pk) for pk in pks}, sort_keys=True)
        if hashes.get(keys_id) == incoming_hashes[keys_id]:
            unchanged.append(item)
        else:
            changed.append(item)
            hashes[keys_id] = incoming_hashes[keys_id]
    if unchanged and table_name in session.info.get(INACTIVE_CONTENT_FLIPS, ()):
        pk_cols = [getattr(model, pk) for pk in primary_keys]
        grouped = defaultdict(list)
        for item in unchanged:
            grouped[item["status"]].append(tuple(item[pk] for pk in primary_keys))
        for status, keys in grouped.items():
            for chunk in chunk_list(keys, 100):
                session.exec(
                    update(model)
                    .where(tuple_(*pk_cols).in_(chunk))
                    .values(status=status, observed_at=model.observed_at)
                )
    if vendor and unchanged:
        vendor.log(
            f"Skipped {len(unchanged)} unchanged {space_after(prefix)}{model_name}(s)."
        )
    items = changed
    if not items:
        return

    if can_bulk_insert(session):
        bulk_insert_items(model, items, vendor, session, progress, prefix)
    else:
        if vendor:
            vendor.progress_tracker.start_task(
                name=f"Syncing {space_after(prefix)}{model_name}(s)", total=len(items)
            )
        if progress:
            pid = progress.add_task(
                f"Inserting {space_after(prefix)}{model_name}(s)", total=len(items)
            )
        for item in items:
            # vendor's auto session.merge doesn't work due to SQLmodel bug:
            # - https://github.com/tiangolo/sqlmodel/issues/6
            # - https://github.com/tiangolo/sqlmodel/issues/342
            # so need to trigger the merge manually
            session.merge(model.model_validate(item))
            if vendor:
                vendor.progress_tracker.advance_task()
            if progress:
                progress.update(pid, advance=1)
        if vendor:
            vendor.progress_tracker.hide_task()
            vendor.log(f"{len(items)} {space_after(prefix)}{model_name}(s) synced.")
