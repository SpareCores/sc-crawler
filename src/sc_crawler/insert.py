from logging import DEBUG
from typing import List, Optional

from sqlalchemy.dialects.sqlite import insert
from sqlmodel import SQLModel

from .schemas import Vendor
from .str import space_after
from .utils import chunk_list, is_sqlite


def validate_items(
    model: SQLModel,
    items: List[dict],
    vendor: Optional[Vendor] = None,
    prefix: str = "",
):
    """Validates a list of items against a SQLModel definition.

    Args:
        model: An SQLModel model to be used for validation.
        items: List of dictionaries to be checked against `model`.
        vendor: Optional Vendor instance used for logging and progress bar updates.
        prefix: Optional extra description for the model added in front of
            the model name in logs and progress bar updates.
    """
    model_name = model.get_table_name()
    if vendor:
        vendor.progress_tracker.start_task(
            name=f"Validating {space_after(prefix)}{model_name}(s)", n=len(items)
        )
    for item in items:
        model.model_validate(item)
        if vendor:
            vendor.progress_tracker.advance_task()
    if vendor:
        vendor.progress_tracker.hide_task()
        vendor.log(
            "%d {space_after(prefix)}%s(s) objects validated"
            % (len(items), model_name),
            DEBUG,
        )


def bulk_insert_items(
    model: SQLModel, items: List[dict], vendor: Vendor, prefix: str = ""
):
    """Bulk inserts items into a SQLModel table with ON CONFLICT update.

    Args:
        model: An SQLModel table definition with primary key(s).
        items: List of dicts with all columns of the model.
        vendor: The related Vendor instance used for database connection, logging and progress bar updates.
        prefix: Optional extra description for the model added in front of
            the model name in logs and progress bar updates.
    """
    model_name = model.get_table_name()
    columns = model.get_columns()
    vendor.progress_tracker.start_task(
        name=f"Syncing {space_after(prefix)}{model_name}(s)", n=len(items)
    )
    # need to split list into smaller chunks to avoid "too many SQL variables"
    for chunk in chunk_list(items, 100):
        query = insert(model).values(chunk)
        query = query.on_conflict_do_update(
            index_elements=[getattr(model, c) for c in columns["primary_keys"]],
            set_={c: query.excluded[c] for c in columns["attributes"]},
        )
        vendor.session.execute(query)
        vendor.progress_tracker.advance_task(by=len(chunk))
    vendor.progress_tracker.hide_task()
    vendor.log(f"{len(items)} {space_after(prefix)}{model_name}(s) synced.")


def insert_items(model: SQLModel, items: List[dict], vendor: Vendor, prefix: str = ""):
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
    model_name = model.get_table_name()
    if is_sqlite(vendor.session):
        validate_items(model, items, vendor, prefix)
        bulk_insert_items(model, items, vendor, prefix)
    else:
        vendor.progress_tracker.start_task(
            name=f"Syncing {space_after(prefix)}{model_name}(s)", n=len(items)
        )
        for item in items:
            # vendor's auto session.merge doesn't work due to SQLmodel bug:
            # - https://github.com/tiangolo/sqlmodel/issues/6
            # - https://github.com/tiangolo/sqlmodel/issues/342
            # so need to trigger the merge manually
            vendor.merge_dependent(model.model_validate(item))
            vendor.progress_tracker.advance_task()
        vendor.progress_tracker.hide_task()
        vendor.log(f"{len(items)} {space_after(prefix)}{model_name}(s) synced.")
