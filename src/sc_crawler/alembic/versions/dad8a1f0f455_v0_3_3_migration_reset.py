"""v0.3.3 migration reset

Revision ID: dad8a1f0f455
Revises:
Create Date: 2026-02-02 17:46:08.598626

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "dad8a1f0f455"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def create_benchmark_table(is_scd: bool):
    is_postgresql_migration = op.get_context().dialect.name == "postgresql"
    json_type = JSONB if is_postgresql_migration else sa.JSON
    table_name = "benchmark_scd" if is_scd else "benchmark"
    primary_key = ("benchmark_id", "observed_at") if is_scd else ("benchmark_id",)
    op.create_table(
        table_name,
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
            json_type(),
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
        sa.PrimaryKeyConstraint(
            *primary_key,
            name=op.f(f"pk_{table_name}"),
        ),
        comment="SCD version of .tables.Benchmark."
        if is_scd
        else "Benchmark scenario definitions.",
    )


def create_compliance_framework_table(is_scd: bool):
    table_name = "compliance_framework_scd" if is_scd else "compliance_framework"
    primary_key = (
        ("compliance_framework_id", "observed_at")
        if is_scd
        else ("compliance_framework_id",)
    )
    op.create_table(
        table_name,
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
        sa.PrimaryKeyConstraint(
            *primary_key,
            name=op.f(f"pk_{table_name}"),
        ),
        comment="SCD version of .tables.ComplianceFramework."
        if is_scd
        else "List of Compliance Frameworks, such as HIPAA or SOC 2 Type 1.",
    )


def create_country_table(is_scd: bool):
    table_name = "country_scd" if is_scd else "country"
    primary_key = ("country_id", "observed_at") if is_scd else ("country_id",)
    op.create_table(
        table_name,
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
        sa.PrimaryKeyConstraint(
            *primary_key,
            name=op.f(f"pk_{table_name}"),
        ),
        comment="SCD version of .tables.Country."
        if is_scd
        else "Country and continent mapping.",
    )


def create_vendor_table(is_scd: bool):
    table_name = "vendor_scd" if is_scd else "vendor"
    primary_key = ("vendor_id", "observed_at") if is_scd else ("vendor_id",)
    country_table_name = "country_scd" if is_scd else "country"
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["country_id"],
                [f"{country_table_name}.country_id"],
                name=op.f(f"fk_{table_name}_country_id_{country_table_name}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        table_name,
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
            comment="4-digit year when the public cloud service of the Vendor was launched.",
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
        *foreign_key,
        sa.PrimaryKeyConstraint(
            *primary_key,
            name=op.f(f"pk_{table_name}"),
        ),
        comment="SCD version of .tables.Vendor."
        if is_scd
        else "Compute resource vendors, such as cloud and server providers.",
    )


def create_region_table(is_scd: bool):
    table_name = "region_scd" if is_scd else "region"
    primary_key = (
        ("vendor_id", "region_id", "observed_at")
        if is_scd
        else (
            "vendor_id",
            "region_id",
        )
    )
    country_table_name = "country_scd" if is_scd else "country"
    vendor_table_name = "vendor_scd" if is_scd else "vendor"
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["country_id"],
                [f"{country_table_name}.country_id"],
                name=op.f(f"fk_{table_name}_country_id_{country_table_name}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table_name}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table_name}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        table_name,
        sa.Column(
            "vendor_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Vendor.",
        ),
        sa.Column(
            "region_id",
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
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depending on the vendor and actual API endpoint.",
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
            comment="List of other commonly used names for the same Region.",
        ),
        sa.Column(
            "country_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Country, where the Region is located.",
        ),
        sa.Column(
            "state",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional state/administrative area of the Region's location within the Country.",
        ),
        sa.Column(
            "city",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional city name of the Region's location.",
        ),
        sa.Column(
            "address_line",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional address line of the Region's location.",
        ),
        sa.Column(
            "zip_code",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional ZIP code of the Region's location.",
        ),
        sa.Column(
            "lon",
            sa.Float(),
            nullable=True,
            comment="Longitude coordinate of the Region's known or approximate location.",
        ),
        sa.Column(
            "lat",
            sa.Float(),
            nullable=True,
            comment="Latitude coordinate of the Region's known or approximate location.",
        ),
        sa.Column(
            "founding_year",
            sa.Integer(),
            nullable=True,
            comment="4-digit year when the Region was founded.",
        ),
        sa.Column(
            "green_energy",
            sa.Boolean(),
            nullable=True,
            comment="If the Region is 100% powered by renewable energy.",
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Region." if is_scd else "Regions of Vendors.",
    )


def create_server_table(is_scd: bool):
    table_name = "server_scd" if is_scd else "server"
    primary_key = (
        ("vendor_id", "server_id", "observed_at")
        if is_scd
        else (
            "vendor_id",
            "server_id",
        )
    )
    vendor_table_name = "vendor_scd" if is_scd else "vendor"
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table_name}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table_name}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        table_name,
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
            "cpu_l1_cache",
            sa.Integer(),
            nullable=True,
            comment="L1 cache size (byte).",
        ),
        sa.Column(
            "cpu_l2_cache",
            sa.Integer(),
            nullable=True,
            comment="L2 cache size (byte).",
        ),
        sa.Column(
            "cpu_l3_cache",
            sa.Integer(),
            nullable=True,
            comment="L3 cache size (byte).",
        ),
        sa.Column(
            "cpu_flags", sa.JSON(), nullable=False, comment="CPU features/flags."
        ),
        sa.Column(
            "cpus",
            sa.JSON(),
            nullable=False,
            comment="JSON array of known CPU details, e.g. the manufacturer, family, model; L1/L2/L3 cache size; microcode version; feature flags; bugs etc.",
        ),
        sa.Column(
            "memory_amount",
            sa.Integer(),
            nullable=False,
            comment="RAM amount (MiB).",
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Server." if is_scd else "Server types.",
    )


def create_storage_table(is_scd: bool):
    table_name = "storage_scd" if is_scd else "storage"
    primary_key = (
        ("vendor_id", "storage_id", "observed_at")
        if is_scd
        else (
            "vendor_id",
            "storage_id",
        )
    )
    vendor_table_name = "vendor_scd" if is_scd else "vendor"
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table_name}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table_name}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        table_name,
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Storage."
        if is_scd
        else "Flexible storage options that can be attached to a Server.",
    )


def create_vendor_compliance_link_table(is_scd: bool):
    table_name = "vendor_compliance_link_scd" if is_scd else "vendor_compliance_link"
    primary_key = (
        ("vendor_id", "compliance_framework_id", "observed_at")
        if is_scd
        else ("vendor_id", "compliance_framework_id")
    )
    compliance_framework_table_name = (
        "compliance_framework_scd" if is_scd else "compliance_framework"
    )
    vendor_table_name = "vendor_scd" if is_scd else "vendor"
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["compliance_framework_id"],
                [f"{compliance_framework_table_name}.compliance_framework_id"],
                name=op.f(
                    f"fk_{table_name}_compliance_framework_id_{compliance_framework_table_name}"
                ),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table_name}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table_name}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        table_name,
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.VendorComplianceLink."
        if is_scd
        else "List of known Compliance Frameworks paired with vendors.",
    )


def create_zone_table(is_scd: bool):
    table_name = "zone_scd" if is_scd else "zone"
    primary_key = (
        ("vendor_id", "region_id", "zone_id", "observed_at")
        if is_scd
        else (
            "vendor_id",
            "region_id",
            "zone_id",
        )
    )
    vendor_table_name = "vendor_scd" if is_scd else "vendor"
    region_table_name = "region_scd" if is_scd else "region"
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id", "region_id"],
                [f"{region_table_name}.vendor_id", f"{region_table_name}.region_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{region_table_name}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table_name}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table_name}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        table_name,
        sa.Column(
            "vendor_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Vendor.",
        ),
        sa.Column(
            "region_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Region.",
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Zone."
        if is_scd
        else "Availability zones of Regions.",
    )


def create_benchmark_score_table(is_scd: bool):
    is_postgresql_migration = op.get_context().dialect.name == "postgresql"
    json_type = JSONB if is_postgresql_migration else sa.JSON
    table_name = "benchmark_score_scd" if is_scd else "benchmark_score"
    primary_key = (
        ("vendor_id", "server_id", "benchmark_id", "config", "observed_at")
        if is_scd
        else ("vendor_id", "server_id", "benchmark_id", "config")
    )
    vendor_table_name = "vendor_scd" if is_scd else "vendor"
    benchmark_table_name = "benchmark_scd" if is_scd else "benchmark"
    server_table_name = "server_scd" if is_scd else "server"
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["benchmark_id"],
                [f"{benchmark_table_name}.benchmark_id"],
                name=op.f(f"fk_{table_name}_benchmark_id_{benchmark_table_name}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table_name}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table_name}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "server_id"],
                [f"{server_table_name}.vendor_id", f"{server_table_name}.server_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{server_table_name}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        table_name,
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
            json_type(),
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.BenchmarkScore."
        if is_scd
        else "Results of running Benchmark scenarios on Servers.",
    )


def create_ipv4_price_table(is_scd: bool):
    table_name = "ipv4_price_scd" if is_scd else "ipv4_price"
    primary_key = (
        ("vendor_id", "region_id", "observed_at")
        if is_scd
        else ("vendor_id", "region_id")
    )
    vendor_table_name = "vendor_scd" if is_scd else "vendor"
    region_table_name = "region_scd" if is_scd else "region"
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table_name}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table_name}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "region_id"],
                [f"{region_table_name}.vendor_id", f"{region_table_name}.region_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{region_table_name}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        table_name,
        sa.Column(
            "vendor_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Vendor.",
        ),
        sa.Column(
            "region_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Region.",
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Ipv4Price."
        if is_scd
        else "Price of an IPv4 address in each Region.",
    )


def create_server_price_table(is_scd: bool):
    table_name = "server_price_scd" if is_scd else "server_price"
    primary_key = (
        ("vendor_id", "region_id", "zone_id", "server_id", "allocation", "observed_at")
        if is_scd
        else ("vendor_id", "region_id", "zone_id", "server_id", "allocation")
    )
    vendor_table_name = "vendor_scd" if is_scd else "vendor"
    region_table_name = "region_scd" if is_scd else "region"
    zone_table_name = "zone_scd" if is_scd else "zone"
    server_table_name = "server_scd" if is_scd else "server"
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table_name}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table_name}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "region_id", "zone_id"],
                [
                    f"{zone_table_name}.vendor_id",
                    f"{zone_table_name}.region_id",
                    f"{zone_table_name}.zone_id",
                ],
                name=op.f(f"fk_{table_name}_vendor_id_{zone_table_name}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "region_id"],
                [
                    f"{region_table_name}.vendor_id",
                    f"{region_table_name}.region_id",
                ],
                name=op.f(f"fk_{table_name}_vendor_id_{region_table_name}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "server_id"],
                [
                    f"{server_table_name}.vendor_id",
                    f"{server_table_name}.server_id",
                ],
                name=op.f(f"fk_{table_name}_vendor_id_{server_table_name}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        table_name,
        sa.Column(
            "vendor_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Vendor.",
        ),
        sa.Column(
            "region_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Region.",
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.ServerPrice."
        if is_scd
        else "Server type prices per Region and Allocation method.",
    )


def create_storage_price_table(is_scd: bool):
    table_name = "storage_price_scd" if is_scd else "storage_price"
    primary_key = (
        ("vendor_id", "region_id", "storage_id", "observed_at")
        if is_scd
        else ("vendor_id", "region_id", "storage_id")
    )
    vendor_table_name = "vendor_scd" if is_scd else "vendor"
    region_table_name = "region_scd" if is_scd else "region"
    storage_table_name = "storage_scd" if is_scd else "storage"
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table_name}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table_name}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "region_id"],
                [
                    f"{region_table_name}.vendor_id",
                    f"{region_table_name}.region_id",
                ],
                name=op.f(f"fk_{table_name}_vendor_id_{region_table_name}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "storage_id"],
                [
                    f"{storage_table_name}.vendor_id",
                    f"{storage_table_name}.storage_id",
                ],
                name=op.f(f"fk_{table_name}_vendor_id_{storage_table_name}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        table_name,
        sa.Column(
            "vendor_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Vendor.",
        ),
        sa.Column(
            "region_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Region.",
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.StoragePrice."
        if is_scd
        else "Flexible Storage prices in each Region.",
    )


def create_traffic_price_table(is_scd: bool):
    table_name = "traffic_price_scd" if is_scd else "traffic_price"
    primary_key = (
        ("vendor_id", "region_id", "direction", "observed_at")
        if is_scd
        else ("vendor_id", "region_id", "direction")
    )
    vendor_table_name = "vendor_scd" if is_scd else "vendor"
    region_table_name = "region_scd" if is_scd else "region"
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table_name}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table_name}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "region_id"],
                [f"{region_table_name}.vendor_id", f"{region_table_name}.region_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{region_table_name}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        table_name,
        sa.Column(
            "vendor_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Vendor.",
        ),
        sa.Column(
            "region_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Region.",
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.TrafficPrice."
        if is_scd
        else "Extra Traffic prices in each Region.",
    )


def upgrade() -> None:
    is_scd = bool(op.get_context().config.attributes.get("scd"))
    create_benchmark_table(is_scd)
    create_compliance_framework_table(is_scd)
    create_country_table(is_scd)
    create_vendor_table(is_scd)
    create_region_table(is_scd)
    create_server_table(is_scd)
    create_storage_table(is_scd)
    create_vendor_compliance_link_table(is_scd)
    create_zone_table(is_scd)
    create_benchmark_score_table(is_scd)
    create_ipv4_price_table(is_scd)
    create_server_price_table(is_scd)
    create_storage_price_table(is_scd)
    create_traffic_price_table(is_scd)


def downgrade() -> None:
    if op.get_context().config.attributes.get("scd"):
        op.drop_table("traffic_price_scd")
        op.drop_table("storage_price_scd")
        op.drop_table("server_price_scd")
        op.drop_table("ipv4_price_scd")
        op.drop_table("benchmark_score_scd")
        op.drop_table("zone_scd")
        op.drop_table("vendor_compliance_link_scd")
        op.drop_table("storage_scd")
        op.drop_table("server_scd")
        op.drop_table("region_scd")
        op.drop_table("vendor_scd")
        op.drop_table("country_scd")
        op.drop_table("compliance_framework_scd")
        op.drop_table("benchmark_scd")
    else:
        op.drop_table("traffic_price")
        op.drop_table("storage_price")
        op.drop_table("server_price")
        op.drop_table("ipv4_price")
        op.drop_table("benchmark_score")
        op.drop_table("zone")
        op.drop_table("vendor_compliance_link")
        op.drop_table("storage")
        op.drop_table("server")
        op.drop_table("region")
        op.drop_table("vendor")
        op.drop_table("country")
        op.drop_table("compliance_framework")
        op.drop_table("benchmark")
