from datetime import datetime
from typing import List

from sqlmodel import Field, SQLModel

from .table_bases import (
    ComplianceFrameworkBase,
    CountryBase,
    DatacenterBase,
    Ipv4PriceBase,
    ScModel,
    ServerBase,
    ServerPriceBase,
    StorageBase,
    StoragePriceBase,
    TrafficPriceBase,
    VendorBase,
    VendorComplianceLinkBase,
    ZoneBase,
)
from .tables import is_table


class Scd(ScModel):
    """Override the `observed_at` column to be primary key in SCD tables."""

    observed_at: datetime = Field(
        primary_key=True,
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        description="Timestamp of the last observation.",
    )


class CountryScd(Scd, CountryBase, table=True):
    pass


class VendorComplianceLinkScd(Scd, VendorComplianceLinkBase, table=True):
    pass


class ComplianceFrameworkScd(Scd, ComplianceFrameworkBase, table=True):
    pass


class VendorScd(Scd, VendorBase, table=True):
    pass


class DatacenterScd(Scd, DatacenterBase, table=True):
    pass


class ZoneScd(Scd, ZoneBase, table=True):
    pass


class StorageScd(Scd, StorageBase, table=True):
    pass


class ServerScd(Scd, ServerBase, table=True):
    pass


class ServerPriceScd(Scd, ServerPriceBase, table=True):
    pass


class StoragePriceScd(Scd, StoragePriceBase, table=True):
    pass


class TrafficPriceScd(Scd, TrafficPriceBase, table=True):
    pass


class Ipv4PriceScd(Scd, Ipv4PriceBase, table=True):
    pass


scd_tables: List[SQLModel] = [o for o in globals().values() if is_table(o)]
"""List of all SCD SQLModel (table) models."""
