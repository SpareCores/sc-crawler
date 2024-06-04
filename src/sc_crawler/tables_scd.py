"""SCD version of the table definitions in [sc_crawler.tables][]."""

from datetime import datetime
from typing import List

from sqlmodel import Field, SQLModel

from .table_bases import (
    BenchmarkBase,
    BenchmarkScoreBase,
    ComplianceFrameworkBase,
    CountryBase,
    Ipv4PriceBase,
    RegionBase,
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
    """SCD version of .tables.VendorComplianceLink."""

    pass


class ComplianceFrameworkScd(Scd, ComplianceFrameworkBase, table=True):
    """SCD version of .tables.ComplianceFramework."""

    pass


class VendorScd(Scd, VendorBase, table=True):
    """SCD version of .tables.Vendor."""

    pass


class RegionScd(Scd, RegionBase, table=True):
    """SCD version of .tables.Region."""

    pass


class ZoneScd(Scd, ZoneBase, table=True):
    """SCD version of .tables.Zone."""

    pass


class StorageScd(Scd, StorageBase, table=True):
    """SCD version of .tables.Storage."""

    pass


class ServerScd(Scd, ServerBase, table=True):
    """SCD version of .tables.Server."""

    pass


class ServerPriceScd(Scd, ServerPriceBase, table=True):
    """SCD version of .tables.ServerPrice."""

    pass


class StoragePriceScd(Scd, StoragePriceBase, table=True):
    """SCD version of .tables.StoragePrice."""

    pass


class TrafficPriceScd(Scd, TrafficPriceBase, table=True):
    """SCD version of .tables.TrafficPrice."""

    pass


class Ipv4PriceScd(Scd, Ipv4PriceBase, table=True):
    """SCD version of .tables.Ipv4Price."""

    pass


class BenchmarkScd(Scd, BenchmarkBase, table=True):
    """SCD version of .tables.Benchmark."""

    pass


class BenchmarkScoreScd(Scd, BenchmarkScoreBase, table=True):
    """SCD version of .tables.BenchmarkScore."""

    pass


tables_scd: List[SQLModel] = [o for o in globals().values() if is_table(o)]
"""List of all SCD SQLModel (table) models."""
