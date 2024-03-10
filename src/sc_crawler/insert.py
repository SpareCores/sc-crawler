from logging import DEBUG
from typing import List, Optional

from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert
from sqlmodel import SQLModel

from .schemas import ServerPrice, ServerPriceBase, Vendor
from .utils import chunk_list, is_sqlite


def validate_items(
    model: BaseModel, items: List[dict], vendor: Optional[Vendor] = None
):
    """Validates a list of items against a pydantic definition.

    Args:
        model: A Pydantic model (e.g. SQLModel without `table=True`) to be used for validation.
        items: List of dictionaries to be checked against `scmodel`.
        vendor: Optional Vendor instance used for logging and progress bar updates.
    """

    # drop the "Base" suffix from class name for better user experience,
    # and as that class will be used by the ORM later anyway
    model_name = model.__name__
    if model_name.endswith("Base"):
        model_name = model_name[: -len("Base")]

    if vendor:
        vendor.progress_tracker.start_task(
            name=f"Validating {model_name}", n=len(items)
        )
    for item in items:
        model.model_validate(item)
        if vendor:
            vendor.progress_tracker.advance_task()
    if vendor:
        vendor.progress_tracker.hide_task()
        vendor.log("%d %s objects validated" % (len(items), model_name), DEBUG)


# def insert_items()


def bulk_insert_items(
    model: SQLModel, items: List[dict], vendor: Vendor, suffix: str = ""
):
    """Bulk inserts items into a SQLModel table with ON CONFLICT update.

    Args:
        model: An SQLModel table definition with primary key(s).
        items: List of dicts with all columns of the model.
        vendor: The related Vendor instance used for database connection, logging and progress bar updates.
        suffix: Optional string added in logs and progress bar updates.
    """
    model_name = model.__name__
    columns = model.get_columns()
    if suffix:
        suffix = f" [{suffix}]"

    vendor.progress_tracker.start_task(
        name=f"Syncing {model_name}{suffix}", n=len(items)
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
    vendor.log(f"{len(items)} {model_name}{suffix} synced.")


def insert_server_prices(server_prices: List[dict], vendor: Vendor, price_type: str):
    """Insert Server Prices into the database using bulk or merge.

    Bulk insert is only supported with SQLite, other databases are using the
    default session.merge (slower) approach.

    Args:
        server_prices: list of dicts with vendor_id, datacenter_id etc (all colums of server_prices)
        vendor: related Vendor instance used for database connection, logging and progress bar updates
        price_type: prefix added in front of "Price" in logs and progress bars
    """
    validate_items(ServerPriceBase, server_prices, vendor)

    if is_sqlite(vendor.session):
        bulk_insert_items(ServerPrice, server_prices, vendor, suffix=price_type)
    else:
        vendor.progress_tracker.start_task(
            name=f"Syncing {price_type} Server Prices", n=len(server_prices)
        )
        for server_price in server_prices:
            # vendor's auto session.merge doesn't work due to SQLmodel bug:
            # - https://github.com/tiangolo/sqlmodel/issues/6
            # - https://github.com/tiangolo/sqlmodel/issues/342
            # so need to trigger the merge manually
            vendor.merge_dependent(ServerPrice.model_validate(server_price))
            vendor.progress_tracker.advance_task()
        vendor.progress_tracker.hide_task()
        vendor.log(f"{len(server_prices)} {price_type} Server Prices synced.")
