"""Data models for the vendor audit.

Two groups of models live here:

- The source list (`sources.yaml`) describing the official vendor pages to audit.
- The structured rows extracted from those pages (by an LLM or a deterministic
  parser), which are compared against our own data.

All extracted values use fixed units, independently of how the vendor
presents them: GiB for memory, GB for disks, Gbps for network, and the
`unit` field for prices.
"""

from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class PageKind(str, Enum):
    """What kind of information a vendor page is authoritative for."""

    SERVER_SPECS = "server_specs"
    SERVER_PRICES = "server_prices"
    COMPONENT_RATES = "component_rates"
    GPU = "gpu"
    DB_SPECS = "db_specs"
    DB_PRICES = "db_prices"
    DB_FEATURES = "db_features"
    REGIONS = "regions"
    LIFECYCLE = "lifecycle"
    INDEX = "index"
    """Navigation only (e.g. a docs table of contents), used to discover pages."""


class FollowLinks(BaseModel):
    """Discover child pages linked from a page, e.g. per-series spec pages."""

    model_config = ConfigDict(extra="forbid")

    pattern: str = Field(description="Regex the absolute child URL must match.")
    kinds: List[PageKind]
    covers: Optional[str] = None
    complete: bool = False
    max_pages: int = 300
    recursive: bool = Field(
        default=False,
        description="Also follow matching links on the child pages (e.g. family to series).",
    )


class SourcePage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description="Unique (per vendor) page identifier, used in file names."
    )
    url: str
    kinds: List[PageKind]
    covers: Optional[str] = Field(
        default=None,
        description="Regex on our SKU ids/names this page is authoritative for.",
    )
    complete: bool = Field(
        default=False,
        description=(
            "The page lists every SKU matching `covers`, so our active SKUs "
            "missing from it can be reported as possibly not existing at the vendor."
        ),
    )
    region: Optional[str] = Field(
        default=None, description="Default region for prices shown on the page."
    )
    currency: Optional[str] = None
    price_region: Optional[str] = Field(
        default=None,
        description=(
            "Region to assume for prices without one, when the vendor's prices are "
            "the same in all regions. Unlike `region`, it doesn't change `complete`."
        ),
    )
    independent: bool = Field(
        default=True,
        description="False if our ingest reads the very same source.",
    )
    spec_authority: bool = Field(
        default=True,
        description=(
            "False if the page's specs are secondary (e.g. a pricing data feed): "
            "its spec mismatches need confirmation by an authoritative page."
        ),
    )
    prices_include_ipv4: bool = Field(
        default=False, description="Listed prices include a public IPv4 address."
    )
    implies_availability: bool = Field(
        default=True,
        description=(
            "A SKU/region listed on the page is actually orderable there. False for "
            "generic price lists covering combinations that may not be sold."
        ),
    )
    parser: Optional[str] = Field(
        default=None,
        description="Name of a deterministic parser to use instead of LLM extraction.",
    )
    follow: Optional[FollowLinks] = None
    notes: Optional[str] = None


class VendorSources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_domains: List[str]
    reference_regions: List[str] = []
    hours_per_month: float = Field(
        default=730, description="Hours used by the vendor for monthly prices."
    )
    monthly_price_is_cap: bool = Field(
        default=False,
        description="Monthly prices are a cap of the hourly billing (see price_tiered).",
    )
    pages: List[SourcePage]


class Sources(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendors: dict[str, VendorSources]


# ##############################################################################
# Extracted rows


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_quote: str = Field(
        description="Verbatim snippet (e.g. a table row) from the page supporting this row."
    )


class ServerSpec(Evidence):
    sku: str = Field(description="SKU / instance type / plan name as on the page.")
    vcpus: Optional[int] = None
    memory_gib: Optional[float] = None
    cpu_manufacturer: Optional[str] = None
    cpu_model: Optional[str] = None
    cpu_speed_ghz: Optional[float] = Field(default=None, description="Max/turbo clock.")
    gpu_count: Optional[float] = None
    gpu_model: Optional[str] = None
    gpu_memory_total_gib: Optional[float] = Field(
        default=None, description="Accelerator memory summed over all GPUs."
    )
    storage_gb: Optional[float] = Field(
        default=None,
        description="Total local/included disk size, 0 if EBS/network only.",
    )
    storage_type: Optional[Literal["hdd", "ssd", "nvme ssd"]] = None
    network_gbps: Optional[float] = Field(
        default=None, description='Maximum ("up to") network bandwidth.'
    )
    status: Optional[
        Literal["active", "unavailable", "previous_generation", "retiring", "retired"]
    ] = Field(
        default=None,
        description="'unavailable': listed, but currently not orderable (e.g. sold out).",
    )


class ServerPrice(Evidence):
    sku: str
    region: Optional[str] = Field(
        default=None, description="Region as on the page; null to use the page default."
    )
    allocation: Literal["ondemand", "spot"] = "ondemand"
    operating_system: Literal["linux", "windows"] = "linux"
    price: float
    unit: Literal["hour", "month"]
    currency: str


class ComponentRate(Evidence):
    target: Literal["server", "database"] = "server"
    sku_prefix: str = Field(
        description="SKU prefix the rate applies to, e.g. 'n2-' or 'db-perf-optimized-N-'."
    )
    region: Optional[str] = None
    allocation: Literal["ondemand", "spot"] = "ondemand"
    component: Literal["vcpu", "memory_gib", "gpu", "local_ssd_gib"]
    ha_level: Optional[Literal["none", "single_zone", "multi_zone"]] = Field(
        default=None,
        description="For database rates only, e.g. 'multi_zone' for regional HA rates.",
    )
    price: float
    unit: Literal["hour", "month"]
    currency: str


class DbSpec(Evidence):
    sku: str
    vcpus: Optional[int] = None
    memory_gib: Optional[float] = None
    storage_gb: Optional[float] = Field(default=None, description="Bundled storage.")


class DbPrice(Evidence):
    sku: str
    region: Optional[str] = None
    ha_level: Optional[Literal["none", "single_zone", "multi_zone"]] = Field(
        default=None, description="Leave null unless the page states it explicitly."
    )
    ha_strategy: Optional[Literal["none", "passive_standby", "readable_cluster"]] = None
    nodes: Optional[int] = None
    deployment: Optional[str] = Field(
        default=None, description="Deployment option as named on the page."
    )
    price: float
    unit: Literal["hour", "month"]
    currency: str


class DbFeature(Evidence):
    feature: Literal[
        "sla",
        "max_read_replicas",
        "continuous_backups_days",
        "engine_versions",
        "storage_extra_max_gb",
    ]
    value: Union[float, int, str, List[str]]
    applies_to: Optional[str] = Field(
        default=None, description="Regex on SKU names if the value is not vendor-wide."
    )


class RegionInfo(Evidence):
    region: str = Field(description="Region code as on the page, e.g. 'eu-central-1'.")
    name: Optional[str] = None
    zone_count: Optional[int] = None


class Extraction(BaseModel):
    """Everything extracted from a single cached vendor page."""

    model_config = ConfigDict(extra="forbid")

    vendor: str
    page_id: str
    extracted_at: datetime
    extracted_by: str = Field(description="E.g. 'claude-code' or a parser name.")
    notes: Optional[str] = Field(
        default=None,
        description="Anything that limits the extraction, e.g. page truncated, JS-rendered.",
    )
    servers: List[ServerSpec] = []
    server_prices: List[ServerPrice] = []
    component_rates: List[ComponentRate] = []
    db_specs: List[DbSpec] = []
    db_prices: List[DbPrice] = []
    db_features: List[DbFeature] = []
    regions: List[RegionInfo] = []
