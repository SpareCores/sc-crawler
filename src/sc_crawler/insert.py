from logging import DEBUG
from typing import List, Optional

from sqlalchemy.dialects.postgresql import insert as insert_postgresql
from sqlalchemy.dialects.sqlite import insert as insert_sqlite
from sqlmodel import Session, SQLModel

from .schemas import Vendor
from .str import space_after
from .utils import chunk_list, is_postgresql, is_sqlite


def can_bulk_insert(session: Session) -> bool:
    """Checks if bulk insert is supported for the engine dialect of a SQLModel session."""
    return is_sqlite(session) or is_postgresql(session)


def validate_items(
    model: SQLModel,
    items: List[dict],
    vendor: Optional[Vendor] = None,
    prefix: str = "",
) -> List[dict]:
    """Validates a list of items against a SQLModel definition.

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
    if vendor:
        vendor.progress_tracker.start_task(
            name=f"Validating {space_after(prefix)}{model_name}(s)", n=len(items)
        )
    for i, item in enumerate(items):
        items[i] = model.model_validate(item).model_dump()
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
    vendor: Optional[Vendor] = None,
    session: Optional[Session] = None,
    prefix: str = "",
):
    """Bulk inserts items into a SQLModel table with ON CONFLICT update.

    Args:
        model: An SQLModel table definition with primary key(s).
        items: List of dicts with all columns of the model.
        vendor: Optional related Vendor instance used for logging and progress bar updates.
        session: Connection for database connections. When not provided, defaults to the `vendor`'s session.
        prefix: Optional extra description for the model added in front of
            the model name in logs and progress bar updates.
    """
    if session is None:
        if vendor is None:
            raise TypeError("At least one of `session` or `vendor` is required.")
        session = vendor.session
    model_name = model.get_table_name()
    columns = model.get_columns()
    if vendor:
        vendor.progress_tracker.start_task(
            name=f"Syncing {space_after(prefix)}{model_name}(s)", n=len(items)
        )
    # need to split list into smaller chunks to avoid "too many SQL variables"
    for chunk in chunk_list(items, 100):
        if is_sqlite(session):
            query = insert_sqlite(model).values(chunk)
        elif is_postgresql(session):
            query = insert_postgresql(model).values(chunk)
        else:
            raise NotImplementedError(
                "Unsupported database engine dialect for bulk inserts."
            )
        query = query.on_conflict_do_update(
            index_elements=[getattr(model, c) for c in columns["primary_keys"]],
            set_={c: query.excluded[c] for c in columns["attributes"]},
        )
        if vendor:
            vendor.session.execute(query)
            vendor.progress_tracker.advance_task(by=len(chunk))
    if vendor:
        vendor.progress_tracker.hide_task()
        vendor.log(f"{len(items)} {space_after(prefix)}{model_name}(s) synced.")


def insert_items(
    model: SQLModel,
    items: List[dict],
    vendor: Optional[Vendor] = None,
    session: Optional[Session] = None,
    prefix: str = "",
):
    """Insert items into the related database table using bulk or merge.

    Bulk insert is only supported with SQLite, other databases fall back to
    the default session.merge (slower) approach.

    Args:
        model: An SQLModel table definition with primary key(s).
        items: List of dicts with all columns of the model.
        vendor: The related Vendor instance used for database connection, logging and progress bar updates.
        prefix: Optional extra description for the model added in front of
            the model name in logs and progress bar updates.
    """
    if session is None:
        if vendor is None:
            raise TypeError("At least one of `session` or `vendor` is required.")
        session = vendor.session
    model_name = model.get_table_name()
    if can_bulk_insert(session):
        items = validate_items(model, items, vendor, prefix)
        bulk_insert_items(model, items, vendor, session, prefix)
    else:
        if vendor:
            vendor.progress_tracker.start_task(
                name=f"Syncing {space_after(prefix)}{model_name}(s)", n=len(items)
            )
        for item in items:
            # vendor's auto session.merge doesn't work due to SQLmodel bug:
            # - https://github.com/tiangolo/sqlmodel/issues/6
            # - https://github.com/tiangolo/sqlmodel/issues/342
            # so need to trigger the merge manually
            session.merge(model.model_validate(item))
            if vendor:
                vendor.progress_tracker.advance_task()
        if vendor:
            vendor.progress_tracker.hide_task()
            vendor.log(f"{len(items)} {space_after(prefix)}{model_name}(s) synced.")
