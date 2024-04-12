"""v0.1.0

Revision ID: 98894dffd37c
Revises:
Create Date: 2024-04-10 00:39:41.172635

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "98894dffd37c"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Lookup context/config attributes:
# - op.get_context().config.attributes.get("scd")


def upgrade() -> None:
    if op.get_context().config.attributes.get("scd"):
        op.create_table(
            "country_scd",
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
            sa.PrimaryKeyConstraint("country_id", "observed_at"),
            comment="SCD version of .tables.Country.",
        )
        op.create_table(
            "compliance_framework_scd",
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
            sa.PrimaryKeyConstraint("compliance_framework_id", "observed_at"),
            comment="SCD version of .tables.ComplianceFrameworkScd.",
        )
        op.create_table(
            "vendor_scd",
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
            sa.ForeignKeyConstraint(
                ["country_id"],
                ["country.country_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "observed_at"),
            comment="SCD version of .tables.VendorScd.",
        )
        op.create_table(
            "vendor_compliance_link_scd",
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
            sa.ForeignKeyConstraint(
                ["compliance_framework_id"],
                ["compliance_framework.compliance_framework_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint(
                "vendor_id", "compliance_framework_id", "observed_at"
            ),
            comment="SCD version of .tables.VendorComplianceLinkScd.",
        )
        op.create_table(
            "datacenter_scd",
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
            sa.ForeignKeyConstraint(
                ["country_id"],
                ["country.country_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "datacenter_id", "observed_at"),
            comment="SCD version of .tables.DatacenterScd.",
        )
        op.create_table(
            "zone_scd",
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
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint(
                "vendor_id", "datacenter_id", "zone_id", "observed_at"
            ),
            comment="SCD version of .tables.ZoneScd.",
        )
        op.create_table(
            "storage_scd",
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
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "storage_id", "observed_at"),
            comment="SCD version of .tables.StorageScd.",
        )
        op.create_table(
            "server_scd",
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
                comment="Human-friendly name or short description.",
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
                nullable=False,
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
                "cpus",
                sa.JSON(),
                nullable=False,
                comment="JSON array of known CPU details, e.g. the manufacturer, family, model; L1/L2/L3 cache size; microcode version; feature flags; bugs etc.",
            ),
            sa.Column(
                "memory", sa.Integer(), nullable=False, comment="RAM amount (MiB)."
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
                comment="The manufacturer of the primary GPU accelerator, e.g. Nvidia or AMD",
            ),
            sa.Column(
                "gpu_model",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
                comment="The model number of the primary GPU accelerator.",
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
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "server_id", "observed_at"),
            comment="SCD version of .tables.ServerScd.",
        )
        op.create_table(
            "server_price_scd",
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
                sa.Enum(
                    "YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"
                ),
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
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint(
                "vendor_id",
                "datacenter_id",
                "zone_id",
                "server_id",
                "allocation",
                "observed_at",
            ),
            comment="SCD version of .tables.ServerPriceScd.",
        )
        op.create_table(
            "storage_price_scd",
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
                sa.Enum(
                    "YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"
                ),
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
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint(
                "vendor_id", "datacenter_id", "storage_id", "observed_at"
            ),
            comment="SCD version of .tables.StoragePriceScd.",
        )
        op.create_table(
            "traffic_price_scd",
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
                sa.Enum(
                    "YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"
                ),
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
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint(
                "vendor_id", "datacenter_id", "direction", "observed_at"
            ),
            comment="SCD version of .tables.TrafficPriceScd.",
        )
        op.create_table(
            "ipv4_price_scd",
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
                sa.Enum(
                    "YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"
                ),
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
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "datacenter_id", "observed_at"),
            comment="SCD version of .tables.Ipv4PriceScd.",
        )
    else:
        op.create_table(
            "country",
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
            sa.PrimaryKeyConstraint("country_id"),
            comment="Country and continent mapping.",
        )
        op.create_table(
            "compliance_framework",
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
            sa.PrimaryKeyConstraint("compliance_framework_id"),
            comment="List of Compliance Frameworks, such as HIPAA or SOC 2 Type 1.",
        )
        op.create_table(
            "vendor",
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
            sa.ForeignKeyConstraint(
                ["country_id"],
                ["country.country_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id"),
            comment="Compute resource vendors, such as cloud and server providers.",
        )
        op.create_table(
            "vendor_compliance_link",
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
            sa.ForeignKeyConstraint(
                ["compliance_framework_id"],
                ["compliance_framework.compliance_framework_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "compliance_framework_id"),
            comment="List of known Compliance Frameworks paired with vendors.",
        )
        op.create_table(
            "datacenter",
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
            sa.ForeignKeyConstraint(
                ["country_id"],
                ["country.country_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "datacenter_id"),
            comment="Datacenters/regions of Vendors.",
        )
        op.create_table(
            "zone",
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
            sa.ForeignKeyConstraint(
                ["vendor_id", "datacenter_id"],
                ["datacenter.vendor_id", "datacenter.datacenter_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "datacenter_id", "zone_id"),
            comment="Availability zones of Datacenters.",
        )
        op.create_table(
            "storage",
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
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "storage_id"),
            comment="Flexible storage options that can be attached to a Server.",
        )
        op.create_table(
            "server",
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
                comment="Human-friendly name or short description.",
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
                nullable=False,
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
                "cpus",
                sa.JSON(),
                nullable=False,
                comment="JSON array of known CPU details, e.g. the manufacturer, family, model; L1/L2/L3 cache size; microcode version; feature flags; bugs etc.",
            ),
            sa.Column(
                "memory", sa.Integer(), nullable=False, comment="RAM amount (MiB)."
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
                comment="The manufacturer of the primary GPU accelerator, e.g. Nvidia or AMD",
            ),
            sa.Column(
                "gpu_model",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
                comment="The model number of the primary GPU accelerator.",
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
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "server_id"),
            comment="Server types.",
        )
        op.create_table(
            "server_price",
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
                sa.Enum(
                    "YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"
                ),
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
            sa.ForeignKeyConstraint(
                ["vendor_id", "datacenter_id", "zone_id"],
                ["zone.vendor_id", "zone.datacenter_id", "zone.zone_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "datacenter_id"],
                ["datacenter.vendor_id", "datacenter.datacenter_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "server_id"],
                ["server.vendor_id", "server.server_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint(
                "vendor_id", "datacenter_id", "zone_id", "server_id", "allocation"
            ),
            comment="Server type prices per Datacenter and Allocation method.",
        )
        op.create_table(
            "storage_price",
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
                sa.Enum(
                    "YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"
                ),
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
            sa.ForeignKeyConstraint(
                ["vendor_id", "datacenter_id"],
                ["datacenter.vendor_id", "datacenter.datacenter_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "storage_id"],
                ["storage.vendor_id", "storage.storage_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "datacenter_id", "storage_id"),
            comment="Flexible Storage prices in each Datacenter.",
        )
        op.create_table(
            "traffic_price",
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
                sa.Enum(
                    "YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"
                ),
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
            sa.ForeignKeyConstraint(
                ["vendor_id", "datacenter_id"],
                ["datacenter.vendor_id", "datacenter.datacenter_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "datacenter_id", "direction"),
            comment="Extra Traffic prices in each Datacenter.",
        )
        op.create_table(
            "ipv4_price",
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
                sa.Enum(
                    "YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"
                ),
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
            sa.ForeignKeyConstraint(
                ["vendor_id", "datacenter_id"],
                ["datacenter.vendor_id", "datacenter.datacenter_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "datacenter_id"),
            comment="Price of an IPv4 address in each Datacenter.",
        )


def downgrade() -> None:
    if op.get_context().config.attributes.get("scd"):
        op.drop_table("ipv4_price_scd")
        op.drop_table("traffic_price_scd")
        op.drop_table("storage_price_scd")
        op.drop_table("server_price_scd")
        op.drop_table("server_scd")
        op.drop_table("storage_scd")
        op.drop_table("zone_scd")
        op.drop_table("datacenter_scd")
        op.drop_table("vendor_compliance_link_scd")
        op.drop_table("vendor_scd")
        op.drop_table("compliance_framework_scd")
        op.drop_table("country_scd")
    else:
        op.drop_table("ipv4_price")
        op.drop_table("traffic_price")
        op.drop_table("storage_price")
        op.drop_table("server_price")
        op.drop_table("server")
        op.drop_table("storage")
        op.drop_table("zone")
        op.drop_table("datacenter")
        op.drop_table("vendor_compliance_link")
        op.drop_table("vendor")
        op.drop_table("compliance_framework")
        op.drop_table("country")
