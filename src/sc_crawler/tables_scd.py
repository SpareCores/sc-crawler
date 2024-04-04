"""SCD version of the table definitions in [sc_crawler.tables][]."""

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
from .table_fields import (
    Allocation,  # noqa: F401 imported for mkdocstrings
    CpuAllocation,  # noqa: F401 imported for mkdocstrings
    CpuArchitecture,  # noqa: F401 imported for mkdocstrings
    PriceUnit,  # noqa: F401 imported for mkdocstrings
    Status,  # noqa: F401 imported for mkdocstrings
    StorageType,  # noqa: F401 imported for mkdocstrings
    TrafficDirection,  # noqa: F401 imported for mkdocstrings
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
    """SCD version of .tables.Country."""

    pass


class VendorComplianceLinkScd(Scd, VendorComplianceLinkBase, table=True):
    """SCD version of .tables.VendorComplianceLinkScd."""

    pass


class ComplianceFrameworkScd(Scd, ComplianceFrameworkBase, table=True):
    """SCD version of .tables.ComplianceFrameworkScd."""

    pass


class VendorScd(Scd, VendorBase, table=True):
    """SCD version of .tables.VendorScd."""

    pass


class DatacenterScd(Scd, DatacenterBase, table=True):
    """SCD version of .tables.DatacenterScd."""

    pass


class ZoneScd(Scd, ZoneBase, table=True):
    """SCD version of .tables.ZoneScd."""

    pass


class StorageScd(Scd, StorageBase, table=True):
    """SCD version of .tables.StorageScd."""

    pass


class ServerScd(Scd, ServerBase, table=True):
    """SCD version of .tables.ServerScd."""

    pass


class ServerPriceScd(Scd, ServerPriceBase, table=True):
    """SCD version of .tables.ServerPriceScd."""

    pass


class StoragePriceScd(Scd, StoragePriceBase, table=True):
    """SCD version of .tables.StoragePriceScd."""

    pass


class TrafficPriceScd(Scd, TrafficPriceBase, table=True):
    """SCD version of .tables.TrafficPriceScd."""

    pass


class Ipv4PriceScd(Scd, Ipv4PriceBase, table=True):
    """SCD version of .tables.Ipv4PriceScd."""

    pass


tables_scd: List[SQLModel] = [o for o in globals().values() if is_table(o)]
"""List of all SCD SQLModel (table) models."""
