"""v1.2.0-name-constraints

Revision ID: 5ae213bf06b3
Revises: 85c7256cc390
Create Date: 2024-06-02 15:44:11.585016

"""

from typing import List, Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5ae213bf06b3"
down_revision: Union[str, None] = "85c7256cc390"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def scdize_suffix(table_name: str) -> str:
    if op.get_context().config.attributes.get("scd"):
        return table_name + "_scd"
    return table_name


def scdize_pk_observed_at(pks: List) -> List:
    if op.get_context().config.attributes.get("scd"):
        return [*pks, "observed_at"]
    return pks


# need to provide the table schema for offline mode support
meta = sa.MetaData()

benchmark_table = sa.Table(
    scdize_suffix("benchmark"),
    meta,
    sa.Column(
        "benchmark_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Unique identifier of a specific Benchmark.",
    ),
    sa.Column(
        "name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly name.",
    ),
    sa.Column(
        "description",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Short description.",
    ),
    sa.Column(
        "framework",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="The name of the benchmark framework/software/tool used.",
    ),
    sa.Column(
        "config_fields",
        sa.JSON(),
        nullable=False,
        comment='A dictionary of descriptions on the framework-specific config options, e.g. {"bandwidth": "Memory amount to use for compression in MB."}.',
    ),
    sa.Column(
        "measurement",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="The name of measurement recoreded in the benchmark.",
    ),
    sa.Column(
        "unit",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional unit of measurement for the benchmark score.",
    ),
    sa.Column(
        "higher_is_better",
        sa.Boolean(),
        nullable=False,
        comment="If higher benchmark score means better performance, or vica versa.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

country_table = sa.Table(
    scdize_suffix("country"),
    meta,
    sa.Column(
        "country_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Country code by ISO 3166 alpha-2.",
    ),
    sa.Column(
        "continent",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Continent name.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

compliance_framework_table = sa.Table(
    scdize_suffix("compliance_framework"),
    meta,
    sa.Column(
        "compliance_framework_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Unique identifier.",
    ),
    sa.Column(
        "name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly name.",
    ),
    sa.Column(
        "abbreviation",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Short abbreviation of the Framework name.",
    ),
    sa.Column(
        "description",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Description of the framework in a few paragrahs, outlining key features and characteristics for reference.",
    ),
    sa.Column(
        "logo",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Publicly accessible URL to the image of the Framework's logo.",
    ),
    sa.Column(
        "homepage",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Public homepage with more information on the Framework.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

vendor_table = sa.Table(
    scdize_suffix("vendor"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Unique identifier.",
    ),
    sa.Column(
        "name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly name.",
    ),
    sa.Column(
        "logo",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Publicly accessible URL to the image of the Vendor's logo.",
    ),
    sa.Column(
        "homepage",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Public homepage of the Vendor.",
    ),
    sa.Column(
        "country_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Country, where the Vendor's main headquarter is located.",
    ),
    sa.Column(
        "state",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional state/administrative area of the Vendor's location within the Country.",
    ),
    sa.Column(
        "city",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional city name of the Vendor's main location.",
    ),
    sa.Column(
        "address_line",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional address line of the Vendor's main location.",
    ),
    sa.Column(
        "zip_code",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional ZIP code of the Vendor's main location.",
    ),
    sa.Column(
        "founding_year",
        sa.Integer(),
        nullable=False,
        comment="4-digit year when the Vendor was founded.",
    ),
    sa.Column(
        "status_page",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Public status page of the Vendor.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

vendor_compliance_link_table = sa.Table(
    scdize_suffix("vendor_compliance_link"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "compliance_framework_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Compliance Framework.",
    ),
    sa.Column(
        "comment",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional references, such as dates, URLs, and additional information/evidence.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)


datacenter_table = sa.Table(
    scdize_suffix("datacenter"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "datacenter_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Unique identifier, as called at the Vendor.",
    ),
    sa.Column(
        "name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly name.",
    ),
    sa.Column(
        "api_reference",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depening on the vendor and actual API endpoint.",
    ),
    sa.Column(
        "display_name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly reference (usually the id or name) of the resource.",
    ),
    sa.Column(
        "aliases",
        sa.JSON(),
        nullable=False,
        comment="List of other commonly used names for the same Datacenter.",
    ),
    sa.Column(
        "country_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Country, where the Datacenter is located.",
    ),
    sa.Column(
        "state",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional state/administrative area of the Datacenter's location within the Country.",
    ),
    sa.Column(
        "city",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional city name of the Datacenter's location.",
    ),
    sa.Column(
        "address_line",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional address line of the Datacenter's location.",
    ),
    sa.Column(
        "zip_code",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional ZIP code of the Datacenter's location.",
    ),
    sa.Column(
        "lon",
        sa.Float(),
        nullable=True,
        comment="Longitude coordinate of the Datacenter's known or approximate location.",
    ),
    sa.Column(
        "lat",
        sa.Float(),
        nullable=True,
        comment="Latitude coordinate of the Datacenter's known or approximate location.",
    ),
    sa.Column(
        "founding_year",
        sa.Integer(),
        nullable=True,
        comment="4-digit year when the Datacenter was founded.",
    ),
    sa.Column(
        "green_energy",
        sa.Boolean(),
        nullable=True,
        comment="If the Datacenter is 100% powered by renewable energy.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

zone_table = sa.Table(
    scdize_suffix("zone"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "datacenter_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Datacenter.",
    ),
    sa.Column(
        "zone_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Unique identifier, as called at the Vendor.",
    ),
    sa.Column(
        "name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly name.",
    ),
    sa.Column(
        "api_reference",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depening on the vendor and actual API endpoint.",
    ),
    sa.Column(
        "display_name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly reference (usually the id or name) of the resource.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

storage_table = sa.Table(
    scdize_suffix("storage"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "storage_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Unique identifier, as called at the Vendor.",
    ),
    sa.Column(
        "name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly name.",
    ),
    sa.Column(
        "description",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Short description.",
    ),
    sa.Column(
        "storage_type",
        sa.Enum("HDD", "SSD", "NVME_SSD", "NETWORK", name="storagetype"),
        nullable=False,
        comment="High-level category of the storage, e.g. HDD or SDD.",
    ),
    sa.Column(
        "max_iops",
        sa.Integer(),
        nullable=True,
        comment="Maximum Input/Output Operations Per Second.",
    ),
    sa.Column(
        "max_throughput",
        sa.Integer(),
        nullable=True,
        comment="Maximum Throughput (MiB/s).",
    ),
    sa.Column(
        "min_size",
        sa.Integer(),
        nullable=True,
        comment="Minimum required size (GiB).",
    ),
    sa.Column(
        "max_size",
        sa.Integer(),
        nullable=True,
        comment="Maximum possible size (GiB).",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

server_table = sa.Table(
    scdize_suffix("server"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "server_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Unique identifier, as called at the Vendor.",
    ),
    sa.Column(
        "name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly name.",
    ),
    sa.Column(
        "api_reference",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depening on the vendor and actual API endpoint.",
    ),
    sa.Column(
        "display_name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly reference (usually the id or name) of the resource.",
    ),
    sa.Column(
        "description",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Short description.",
    ),
    sa.Column(
        "family",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Server family, e.g. General-purpose machine (GCP), or M5g (AWS).",
    ),
    sa.Column(
        "vcpus",
        sa.Integer(),
        nullable=False,
        comment="Default number of virtual CPUs (vCPU) of the server.",
    ),
    sa.Column(
        "hypervisor",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Hypervisor of the virtual server, e.g. Xen, KVM, Nitro or Dedicated.",
    ),
    sa.Column(
        "cpu_allocation",
        sa.Enum("SHARED", "BURSTABLE", "DEDICATED", name="cpuallocation"),
        nullable=False,
        comment="Allocation of CPU(s) to the server, e.g. shared, burstable or dedicated.",
    ),
    sa.Column(
        "cpu_cores",
        sa.Integer(),
        nullable=True,
        comment="Default number of CPU cores of the server. Equals to vCPUs when HyperThreading is disabled.",
    ),
    sa.Column(
        "cpu_speed",
        sa.Float(),
        nullable=True,
        comment="Vendor-reported maximum CPU clock speed (GHz).",
    ),
    sa.Column(
        "cpu_architecture",
        sa.Enum(
            "ARM64",
            "ARM64_MAC",
            "I386",
            "X86_64",
            "X86_64_MAC",
            name="cpuarchitecture",
        ),
        nullable=False,
        comment="CPU architecture (arm64, arm64_mac, i386, or x86_64).",
    ),
    sa.Column(
        "cpu_manufacturer",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="The manufacturer of the primary processor, e.g. Intel or AMD.",
    ),
    sa.Column(
        "cpu_family",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="The product line/family of the primary processor, e.g. Xeon, Core i7, Ryzen 9.",
    ),
    sa.Column(
        "cpu_model",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="The model number of the primary processor, e.g. 9750H.",
    ),
    sa.Column(
        "cpu_l1_cache", sa.Integer(), nullable=True, comment="L1 cache size (MiB)."
    ),
    sa.Column(
        "cpu_l2_cache", sa.Integer(), nullable=True, comment="L2 cache size (MiB)."
    ),
    sa.Column(
        "cpu_l3_cache", sa.Integer(), nullable=True, comment="L3 cache size (MiB)."
    ),
    sa.Column("cpu_flags", sa.JSON(), nullable=False, comment="CPU features/flags."),
    sa.Column(
        "cpus",
        sa.JSON(),
        nullable=False,
        comment="JSON array of known CPU details, e.g. the manufacturer, family, model; L1/L2/L3 cache size; microcode version; feature flags; bugs etc.",
    ),
    sa.Column(
        "memory_amount", sa.Integer(), nullable=False, comment="RAM amount (MiB)."
    ),
    sa.Column(
        "memory_generation",
        sa.Enum("DDR3", "DDR4", "DDR5", name="ddrgeneration"),
        nullable=True,
        comment="Generation of the DDR SDRAM, e.g. DDR4 or DDR5.",
    ),
    sa.Column(
        "memory_speed",
        sa.Integer(),
        nullable=True,
        comment="DDR SDRAM clock rate (Mhz).",
    ),
    sa.Column(
        "memory_ecc",
        sa.Boolean(),
        nullable=True,
        comment="If the DDR SDRAM uses error correction code to detect and correct n-bit data corruption.",
    ),
    sa.Column(
        "gpu_count",
        sa.Integer(),
        nullable=False,
        comment="Number of GPU accelerator(s).",
    ),
    sa.Column(
        "gpu_memory_min",
        sa.Integer(),
        nullable=True,
        comment="Memory (MiB) allocated to the lowest-end GPU accelerator.",
    ),
    sa.Column(
        "gpu_memory_total",
        sa.Integer(),
        nullable=True,
        comment="Overall memory (MiB) allocated to all the GPU accelerator(s).",
    ),
    sa.Column(
        "gpu_manufacturer",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="The manufacturer of the primary GPU accelerator, e.g. Nvidia or AMD.",
    ),
    sa.Column(
        "gpu_family",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="The product family of the primary GPU accelerator, e.g. Turing.",
    ),
    sa.Column(
        "gpu_model",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="The model number of the primary GPU accelerator, e.g. Tesla T4.",
    ),
    sa.Column(
        "gpus",
        sa.JSON(),
        nullable=False,
        comment="JSON array of GPU accelerator details, including the manufacturer, name, and memory (MiB) of each GPU.",
    ),
    sa.Column(
        "storage_size",
        sa.Integer(),
        nullable=False,
        comment="Overall size (GB) of the disk(s).",
    ),
    sa.Column(
        "storage_type",
        sa.Enum("HDD", "SSD", "NVME_SSD", "NETWORK", name="storagetype"),
        nullable=True,
        comment="Primary disk type, e.g. HDD, SSD, NVMe SSD, or network).",
    ),
    sa.Column(
        "storages",
        sa.JSON(),
        nullable=False,
        comment="JSON array of disks attached to the server, including the size (MiB) and type of each disk.",
    ),
    sa.Column(
        "network_speed",
        sa.Float(),
        nullable=True,
        comment="The baseline network performance (Gbps) of the network card.",
    ),
    sa.Column(
        "inbound_traffic",
        sa.Float(),
        nullable=False,
        comment="Amount of complimentary inbound traffic (GB) per month.",
    ),
    sa.Column(
        "outbound_traffic",
        sa.Float(),
        nullable=False,
        comment="Amount of complimentary outbound traffic (GB) per month.",
    ),
    sa.Column(
        "ipv4",
        sa.Integer(),
        nullable=False,
        comment="Number of complimentary IPv4 address(es).",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

server_price_table = sa.Table(
    scdize_suffix("server_price"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "datacenter_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Datacenter.",
    ),
    sa.Column(
        "zone_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Zone.",
    ),
    sa.Column(
        "server_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Server.",
    ),
    sa.Column(
        "operating_system",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Operating System.",
    ),
    sa.Column(
        "allocation",
        sa.Enum("ONDEMAND", "RESERVED", "SPOT", name="allocation"),
        nullable=False,
        comment="Allocation method, e.g. on-demand or spot.",
    ),
    sa.Column(
        "unit",
        sa.Enum("YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"),
        nullable=False,
        comment="Billing unit of the pricing model.",
    ),
    sa.Column(
        "price",
        sa.Float(),
        nullable=False,
        comment="Actual price of a billing unit.",
    ),
    sa.Column(
        "price_upfront",
        sa.Float(),
        nullable=False,
        comment="Price to be paid when setting up the resource.",
    ),
    sa.Column(
        "price_tiered",
        sa.JSON(),
        nullable=False,
        comment="List of pricing tiers with min/max thresholds and actual prices.",
    ),
    sa.Column(
        "currency",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Currency of the prices.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

storage_price_table = sa.Table(
    scdize_suffix("storage_price"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "datacenter_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Datacenter.",
    ),
    sa.Column(
        "storage_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Storage.",
    ),
    sa.Column(
        "unit",
        sa.Enum("YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"),
        nullable=False,
        comment="Billing unit of the pricing model.",
    ),
    sa.Column(
        "price",
        sa.Float(),
        nullable=False,
        comment="Actual price of a billing unit.",
    ),
    sa.Column(
        "price_upfront",
        sa.Float(),
        nullable=False,
        comment="Price to be paid when setting up the resource.",
    ),
    sa.Column(
        "price_tiered",
        sa.JSON(),
        nullable=False,
        comment="List of pricing tiers with min/max thresholds and actual prices.",
    ),
    sa.Column(
        "currency",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Currency of the prices.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

traffic_price_table = sa.Table(
    scdize_suffix("traffic_price"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "datacenter_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Datacenter.",
    ),
    sa.Column(
        "direction",
        sa.Enum("IN", "OUT", name="trafficdirection"),
        nullable=False,
        comment="Direction of the traffic: inbound or outbound.",
    ),
    sa.Column(
        "unit",
        sa.Enum("YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"),
        nullable=False,
        comment="Billing unit of the pricing model.",
    ),
    sa.Column(
        "price",
        sa.Float(),
        nullable=False,
        comment="Actual price of a billing unit.",
    ),
    sa.Column(
        "price_upfront",
        sa.Float(),
        nullable=False,
        comment="Price to be paid when setting up the resource.",
    ),
    sa.Column(
        "price_tiered",
        sa.JSON(),
        nullable=False,
        comment="List of pricing tiers with min/max thresholds and actual prices.",
    ),
    sa.Column(
        "currency",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Currency of the prices.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

ipv4_price_table = sa.Table(
    scdize_suffix("ipv4_price"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "datacenter_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Datacenter.",
    ),
    sa.Column(
        "unit",
        sa.Enum("YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"),
        nullable=False,
        comment="Billing unit of the pricing model.",
    ),
    sa.Column(
        "price",
        sa.Float(),
        nullable=False,
        comment="Actual price of a billing unit.",
    ),
    sa.Column(
        "price_upfront",
        sa.Float(),
        nullable=False,
        comment="Price to be paid when setting up the resource.",
    ),
    sa.Column(
        "price_tiered",
        sa.JSON(),
        nullable=False,
        comment="List of pricing tiers with min/max thresholds and actual prices.",
    ),
    sa.Column(
        "currency",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Currency of the prices.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)

benchmark_score_table = sa.Table(
    scdize_suffix("benchmark_score"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "server_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Server.",
    ),
    sa.Column(
        "benchmark_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Benchmark.",
    ),
    sa.Column(
        "config",
        sa.JSON(),
        nullable=False,
        comment='Dictionary of config parameters of the specific benchmark, e.g. {"bandwidth": 4096}',
    ),
    sa.Column(
        "score",
        sa.Float(),
        nullable=False,
        comment="The resulting score of the benchmark.",
    ),
    sa.Column(
        "note",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional note, comment or context on the benchmark score.",
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    ),
)


def upgrade() -> None:
    """Recreate tables with named constraints.

    Need to recreate all tables with the PKs and FKs to name those, as
    all were created without a name previously, and there is no way to
    reference those in Alembic for future deletion/updates. Now with
    automatic naming schema, this should be fixed for the future.

    References: https://alembic.sqlalchemy.org/en/latest/naming.html
    """
    with op.batch_alter_table(
        scdize_suffix("benchmark_framework"),
        schema=None,
        copy_from=benchmark_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_benchmark")),
            scdize_pk_observed_at(["benchmark_id"]),
        )

    with op.batch_alter_table(
        scdize_suffix("compliance_framework"),
        schema=None,
        copy_from=compliance_framework_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_compliance_framework")),
            scdize_pk_observed_at(["compliance_framework_id"]),
        )

    with op.batch_alter_table(
        scdize_suffix("country_framework"),
        schema=None,
        copy_from=country_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_country")),
            scdize_pk_observed_at(["country_id"]),
        )

    with op.batch_alter_table(
        scdize_suffix("vendor"),
        schema=None,
        copy_from=vendor_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_vendor")),
            scdize_pk_observed_at(["vendor_id"]),
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('vendor')}_country_id_country")),
            "country",
            ["country_id"],
            ["country_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("vendor_compliance_link"),
        schema=None,
        copy_from=vendor_compliance_link_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_vendor_compliance_link")),
            scdize_pk_observed_at(["vendor_id", "compliance_framework_id"]),
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(
                    f"fk_{scdize_suffix('vendor_compliance_link')}_compliance_framework_id_compliance_framework"
                )
            ),
            "compliance_framework",
            ["compliance_framework_id"],
            ["compliance_framework_id"],
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(
                    f"fk_{scdize_suffix('vendor_compliance_link')}_vendor_id_vendor"
                )
            ),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("datacenter"),
        schema=None,
        copy_from=datacenter_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_datacenter")),
            scdize_pk_observed_at(["vendor_id", "datacenter_id"]),
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('datacenter')}_country_id_country")),
            "country",
            ["country_id"],
            ["country_id"],
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('datacenter')}_vendor_id_vendor")),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("zone"),
        schema=None,
        copy_from=zone_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_zone")),
            scdize_pk_observed_at(["vendor_id", "datacenter_id", "zone_id"]),
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('zone')}_vendor_id_datacenter")),
            "datacenter",
            ["vendor_id", "datacenter_id"],
            ["vendor_id", "datacenter_id"],
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('zone')}_vendor_id_vendor")),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("storage"),
        schema=None,
        copy_from=storage_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_storage")),
            scdize_pk_observed_at(["vendor_id", "storage_id"]),
        )

        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('storage')}_vendor_id_vendor")),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("server"),
        schema=None,
        copy_from=server_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_server")),
            scdize_pk_observed_at(["vendor_id", "server_id"]),
        )

        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('server')}_vendor_id_vendor")),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("server_price"),
        schema=None,
        copy_from=server_price_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_server_price")),
            scdize_pk_observed_at(
                ["vendor_id", "datacenter_id", "zone_id", "server_id", "allocation"]
            ),
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('server_price')}_vendor_id_vendor")),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(
                    f"fk_{scdize_suffix('server_price')}_vendor_id_datacenter"
                )
            ),
            "datacenter",
            ["vendor_id", "datacenter_id"],
            ["vendor_id", "datacenter_id"],
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('server_price')}_vendor_id_zone")),
            "zone",
            ["vendor_id", "datacenter_id", "zone_id"],
            ["vendor_id", "datacenter_id", "zone_id"],
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('server_price')}_vendor_id_server")),
            "server",
            ["vendor_id", "server_id"],
            ["vendor_id", "server_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("storage_price"),
        schema=None,
        copy_from=storage_price_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_storage_price")),
            scdize_pk_observed_at(["vendor_id", "datacenter_id", "storage_id"]),
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(f"fk_{scdize_suffix('storage_price')}_vendor_id_vendor")
            ),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(
                    f"fk_{scdize_suffix('storage_price')}_vendor_id_datacenter"
                )
            ),
            "datacenter",
            ["vendor_id", "datacenter_id"],
            ["vendor_id", "datacenter_id"],
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(f"fk_{scdize_suffix('storage_price')}_vendor_id_storage")
            ),
            "storage",
            ["vendor_id", "storage_id"],
            ["vendor_id", "storage_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("traffic_price"),
        schema=None,
        copy_from=traffic_price_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_traffic_price")),
            scdize_pk_observed_at(["vendor_id", "datacenter_id", "direction"]),
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(f"fk_{scdize_suffix('traffic_price')}_vendor_id_vendor")
            ),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(
                    f"fk_{scdize_suffix('traffic_price')}_vendor_id_datacenter"
                )
            ),
            "datacenter",
            ["vendor_id", "datacenter_id"],
            ["vendor_id", "datacenter_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("ipv4_price"),
        schema=None,
        copy_from=ipv4_price_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_ipv4_price")),
            scdize_pk_observed_at(["vendor_id", "datacenter_id"]),
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('ipv4_price')}_vendor_id_vendor")),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(f"fk_{scdize_suffix('ipv4_price')}_vendor_id_datacenter")
            ),
            "datacenter",
            ["vendor_id", "datacenter_id"],
            ["vendor_id", "datacenter_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("benchmark_score"),
        schema=None,
        copy_from=benchmark_score_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_benchmark_score")),
            scdize_pk_observed_at(["vendor_id", "server_id", "benchmark_id", "config"]),
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(f"fk_{scdize_suffix('benchmark_score')}_vendor_id_vendor")
            ),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(f"fk_{scdize_suffix('benchmark_score')}_server_id_vendor")
            ),
            "server",
            ["vendor_id", "server_id"],
            ["vendor_id", "server_id"],
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(
                    f"fk_{scdize_suffix('benchmark_score')}_benchmark_id_benchmark"
                )
            ),
            "benchmark",
            ["benchmark_id"],
            ["benchmark_id"],
        )


def downgrade() -> None:
    # upgrade only name the already existing constraints, no revert needed/can be done
    pass
