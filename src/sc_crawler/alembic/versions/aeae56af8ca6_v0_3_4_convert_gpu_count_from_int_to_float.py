"""v0.3.4 convert gpu_count from int to float

Revision ID: aeae56af8ca6
Revises: dad8a1f0f455
Create Date: 2026-01-30 20:14:29.156914

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aeae56af8ca6"
down_revision: Union[str, None] = "dad8a1f0f455"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def get_benchmark_table(is_scd: bool) -> sa.Table:
    table_name = "benchmark_scd" if is_scd else "benchmark"
    primary_key = ("benchmark_id", "observed_at") if is_scd else ("benchmark_id",)
    is_postgresql_migration = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql_migration else sa.JSON
    return sa.Table(
        table_name,
        sa.MetaData(),
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
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
    )


def get_compliance_framework_table(is_scd: bool) -> sa.Table:
    table_name = "compliance_framework_scd" if is_scd else "compliance_framework"
    primary_key = (
        ("compliance_framework_id", "observed_at")
        if is_scd
        else ("compliance_framework_id",)
    )
    return sa.Table(
        table_name,
        sa.MetaData(),
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
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
    )


def get_server_table(is_scd: bool) -> sa.Table:
    table_name = "server_scd" if is_scd else "server"
    primary_key = (
        ("vendor_id", "server_id", "observed_at")
        if is_scd
        else ("vendor_id", "server_id")
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
    return sa.Table(
        table_name,
        sa.MetaData(),
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
            "cpu_l1_cache", sa.Integer(), nullable=True, comment="L1 cache size (byte)."
        ),
        sa.Column(
            "cpu_l2_cache", sa.Integer(), nullable=True, comment="L2 cache size (byte)."
        ),
        sa.Column(
            "cpu_l3_cache", sa.Integer(), nullable=True, comment="L3 cache size (byte)."
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
    )


def get_zone_table(is_scd: bool) -> sa.Table:
    table_name = "zone_scd" if is_scd else "zone"
    primary_key = (
        ("vendor_id", "region_id", "zone_id", "observed_at")
        if is_scd
        else ("vendor_id", "region_id", "zone_id")
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
    return sa.Table(
        table_name,
        sa.MetaData(),
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
    )


def upgrade() -> None:
    benchmark_table_name = scdize_suffix("benchmark")
    compliance_framework_table_name = scdize_suffix("compliance_framework")
    server_table_name = scdize_suffix("server")
    zone_table_name = scdize_suffix("zone")
    benchmark_table: sa.Table = get_benchmark_table(is_scd_migration())
    compliance_framework_table: sa.Table = get_compliance_framework_table(
        is_scd_migration()
    )
    server_table: sa.Table = get_server_table(is_scd_migration())
    zone_table: sa.Table = get_zone_table(is_scd_migration())
    with op.batch_alter_table(
        server_table_name,
        schema=None,
        copy_from=server_table,
    ) as batch_op:
        batch_op.alter_column(
            "gpu_count",
            existing_type=sa.INTEGER(),
            type_=sa.Float(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "api_reference",
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depending on the vendor and actual API endpoint.",
        )
    with op.batch_alter_table(
        benchmark_table_name, schema=None, copy_from=benchmark_table
    ) as batch_op:
        batch_op.alter_column(
            "measurement",
            comment="The name of measurement recorded in the benchmark.",
        )
    with op.batch_alter_table(
        zone_table_name, schema=None, copy_from=zone_table
    ) as batch_op:
        batch_op.alter_column(
            "api_reference",
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depending on the vendor and actual API endpoint.",
        )
    with op.batch_alter_table(
        compliance_framework_table_name,
        schema=None,
        copy_from=compliance_framework_table,
    ) as batch_op:
        batch_op.alter_column(
            "description",
            comment="Description of the framework in a few paragraphs, outlining key features and characteristics for reference.",
        )


def downgrade() -> None:
    benchmark_table_name = scdize_suffix("benchmark")
    compliance_framework_table_name = scdize_suffix("compliance_framework")
    server_table_name = scdize_suffix("server")
    zone_table_name = scdize_suffix("zone")
    benchmark_table: sa.Table = get_benchmark_table(is_scd_migration())
    compliance_framework_table: sa.Table = get_compliance_framework_table(
        is_scd_migration()
    )
    server_table: sa.Table = get_server_table(is_scd_migration())
    zone_table: sa.Table = get_zone_table(is_scd_migration())
    with op.batch_alter_table(
        server_table_name, schema=None, copy_from=server_table
    ) as batch_op:
        batch_op.alter_column(
            "gpu_count",
            existing_type=sa.Float(),
            type_=sa.INTEGER(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "api_reference",
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depening on the vendor and actual API endpoint.",
        )
    with op.batch_alter_table(
        benchmark_table_name, schema=None, copy_from=benchmark_table
    ) as batch_op:
        batch_op.alter_column(
            "measurement",
            comment="The name of measurement recoreded in the benchmark.",
        )
    with op.batch_alter_table(
        zone_table_name, schema=None, copy_from=zone_table
    ) as batch_op:
        batch_op.alter_column(
            "api_reference",
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depening on the vendor and actual API endpoint.",
        )
    with op.batch_alter_table(
        compliance_framework_table_name,
        schema=None,
        copy_from=compliance_framework_table,
    ) as batch_op:
        batch_op.alter_column(
            "description",
            comment="Description of the framework in a few paragrahs, outlining key features and characteristics for reference.",
        )
