"""v0.12.0 add retirement_date to server and database

Revision ID: 67f053fde65f
Revises: 64c7aace12bf
Create Date: 2026-11-21 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "67f053fde65f"
down_revision: Union[str, None] = "64c7aace12bf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COMMENT = (
    "Retirement date announced by the vendor for PLANNED_FOR_RETIREMENT "
    "and RETIRED records: the end of support (shutdown) if published, "
    "otherwise the end of sale. Empty when not announced or not known."
)

# table -> (name of the SKU id column, the column the new one is added after)
_TABLES = {
    "server": ("server_id", "average_time_to_start"),
    "database": ("database_id", "security_features"),
}


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def _enum(name: str, values: tuple[str, ...]):
    is_postgresql = op.get_context().dialect.name == "postgresql"
    if is_postgresql:
        return sa.dialects.postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


def _new_column() -> sa.Column:
    return sa.Column("retirement_date", sa.Date(), nullable=True, comment=_COMMENT)


def _server_columns(json_type) -> tuple:
    return (
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
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depending on the vendor and actual API endpoint.",
        ),
        sa.Column(
            "api_reference_object",
            json_type(none_as_null=True),
            nullable=True,
            comment="How this resource is referenced in the vendor API calls, including the parameter name(s).",
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
            nullable=False,
            comment="Short description.",
        ),
        sa.Column(
            "family",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Broad workload class of the server in the vendor's own naming, e.g. General Purpose, Compute Optimized or Memory Optimized.",
        ),
        sa.Column(
            "series",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Hardware line and generation of the server, e.g. m5 (AWS), n2 (GCP) or b3 (OVH).",
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
            _enum(
                "cpuallocation",
                (
                    "SHARED",
                    "BURSTABLE",
                    "DEDICATED",
                ),
            ),
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
            _enum(
                "cpuarchitecture",
                (
                    "ARM64",
                    "ARM64_MAC",
                    "I386",
                    "X86_64",
                    "X86_64_MAC",
                ),
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
            "cpu_l1d_cache",
            sa.Integer(),
            nullable=True,
            comment="L1 data cache size (KiB).",
        ),
        sa.Column(
            "cpu_l1d_cache_total",
            sa.Integer(),
            nullable=True,
            comment="Total L1 data cache size (KiB) across all cores.",
        ),
        sa.Column(
            "cpu_l1i_cache",
            sa.Integer(),
            nullable=True,
            comment="L1 instruction cache size (KiB).",
        ),
        sa.Column(
            "cpu_l1i_cache_total",
            sa.Integer(),
            nullable=True,
            comment="Total L1 instruction cache size (KiB) across all cores.",
        ),
        sa.Column(
            "cpu_l2_cache",
            sa.Integer(),
            nullable=True,
            comment="L2 cache size (KiB).",
        ),
        sa.Column(
            "cpu_l2_cache_total",
            sa.Integer(),
            nullable=True,
            comment="Total L2 cache size (KiB) across all cores.",
        ),
        sa.Column(
            "cpu_l3_cache",
            sa.Integer(),
            nullable=True,
            comment="L3 cache size (KiB).",
        ),
        sa.Column(
            "cpu_l3_cache_total",
            sa.Integer(),
            nullable=True,
            comment="Total L3 cache size (KiB) across all cores.",
        ),
        sa.Column(
            "cpu_flags",
            json_type(),
            nullable=False,
            comment="CPU features/flags.",
        ),
        sa.Column(
            "cpus",
            json_type(),
            nullable=False,
            comment="JSON array of known CPU details, e.g. the manufacturer, family, model; L1/L2/L3 cache size; microcode version; feature flags; bugs etc.",
        ),
        sa.Column(
            "ecpus",
            sa.Float(),
            nullable=True,
            comment='The effective "real-world" core count, calculated by dividing the maximum multi-core SCore by the single-core SCore.',
        ),
        sa.Column(
            "scalability",
            sa.Float(),
            nullable=True,
            comment="Measures how efficiently the server scales from a single core performance to using multiple cores. A score of 100% means perfect linear scaling with zero performance loss.",
        ),
        sa.Column(
            "hw_virt",
            sa.Boolean(),
            nullable=True,
            comment="If hardware virtualization (e.g. KVM) is supported.",
        ),
        sa.Column(
            "memory_amount",
            sa.Integer(),
            nullable=False,
            comment="RAM amount (MiB) reported by the vendor.",
        ),
        sa.Column(
            "memory_amount_actual",
            sa.Integer(),
            nullable=True,
            comment="Actual RAM amount (MiB) measured on the instance via lstopo or other tool. This amount might not match the vendor-reported memory due to the BIOS or the hypervisor reserving a small percentage.",
        ),
        sa.Column(
            "memory_generation",
            _enum(
                "ddrgeneration",
                (
                    "DDR3",
                    "DDR4",
                    "DDR5",
                ),
            ),
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
            "accelerator_count",
            sa.Float(),
            nullable=False,
            comment="Number of accelerator(s), e.g. GPUs or NPUs.",
        ),
        sa.Column(
            "accelerator_memory_min",
            sa.Integer(),
            nullable=True,
            comment="Memory (MiB) allocated to the lowest-end accelerator.",
        ),
        sa.Column(
            "accelerator_memory_total",
            sa.Integer(),
            nullable=True,
            comment="Overall memory (MiB) allocated to all the accelerator(s).",
        ),
        sa.Column(
            "accelerator_type",
            _enum(
                "acceleratortype",
                (
                    "GPU",
                    "TPU",
                    "NPU",
                    "FPGA",
                    "VPU",
                ),
            ),
            nullable=True,
            comment="The type of the primary accelerator, e.g. GPU or NPU.",
        ),
        sa.Column(
            "accelerator_manufacturer",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="The manufacturer of the primary accelerator, e.g. Nvidia or AMD.",
        ),
        sa.Column(
            "accelerator_family",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="The product family of the primary accelerator, e.g. Turing.",
        ),
        sa.Column(
            "accelerator_model",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="The model number of the primary accelerator, e.g. Tesla T4.",
        ),
        sa.Column(
            "accelerators",
            json_type(),
            nullable=False,
            comment="JSON array of accelerator details, including the manufacturer, name, and memory (MiB) of each accelerator.",
        ),
        sa.Column(
            "storage_size",
            sa.Integer(),
            nullable=False,
            comment="Overall size (GB) of the disk(s).",
        ),
        sa.Column(
            "storage_type",
            _enum(
                "storagetype",
                (
                    "HDD",
                    "SSD",
                    "NVME_SSD",
                ),
            ),
            nullable=True,
            comment="Primary disk type, e.g. HDD, SSD, or NVMe SSD.",
        ),
        sa.Column(
            "storages",
            json_type(),
            nullable=False,
            comment="JSON array of disks attached to the server, including the size (GB) and type of each disk.",
        ),
        sa.Column(
            "storage_read_iops_max",
            sa.Integer(),
            nullable=True,
            comment="The vendor-published maximum read IOPS of the bundled disk(s), summed over all disks, also of different types (e.g. temp disk and NVMe), so a theoretical total. Per-disk values are in storages.",
        ),
        sa.Column(
            "storage_write_iops_max",
            sa.Integer(),
            nullable=True,
            comment="The vendor-published maximum write IOPS of the bundled disk(s), summed over all disks, also of different types (e.g. temp disk and NVMe), so a theoretical total. Per-disk values are in storages.",
        ),
        sa.Column(
            "storage_read_throughput_max",
            sa.Integer(),
            nullable=True,
            comment="The vendor-published maximum read throughput (MB/s) of the bundled disk(s), summed over all disks, also of different types (e.g. temp disk and NVMe), so a theoretical total. Per-disk values are in storages.",
        ),
        sa.Column(
            "storage_write_throughput_max",
            sa.Integer(),
            nullable=True,
            comment="The vendor-published maximum write throughput (MB/s) of the bundled disk(s), summed over all disks, also of different types (e.g. temp disk and NVMe), so a theoretical total. Per-disk values are in storages.",
        ),
        sa.Column(
            "compatible_storage_ids",
            json_type(none_as_null=True),
            nullable=True,
            comment="List of storage_ids that can be attached to the server as extra storage.",
        ),
        sa.Column(
            "network_speed_baseline",
            sa.Float(),
            nullable=True,
            comment="The baseline network performance (Gbps) of the server, aggregated over all network cards.",
        ),
        sa.Column(
            "network_speed_max",
            sa.Float(),
            nullable=True,
            comment="The maximum network performance (Gbps) of the server, aggregated over all network cards.",
        ),
        sa.Column(
            "network_storage_speed_baseline",
            sa.Float(),
            nullable=True,
            comment="The baseline bandwidth performance of network-attached storage (Gbps).",
        ),
        sa.Column(
            "network_storage_speed_max",
            sa.Float(),
            nullable=True,
            comment="The maximum bandwidth performance of network-attached storage (Gbps).",
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
            "average_time_to_start",
            sa.Float(),
            nullable=True,
            comment="Average time to start the server (seconds).",
        ),
        sa.Column(
            "status",
            _enum(
                "status",
                (
                    "ACTIVE",
                    "INACTIVE",
                    "PLANNED_FOR_RETIREMENT",
                    "RETIRED",
                    "ARCHIVED",
                ),
            ),
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


def _database_columns(json_type) -> tuple:
    return (
        sa.Column(
            "vendor_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Vendor.",
        ),
        sa.Column(
            "database_id",
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
            "api_reference_object",
            json_type(none_as_null=True),
            nullable=True,
            comment="How this resource is referenced in the vendor API calls, including the parameter name(s).",
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
            comment="Broad workload class of the database in the vendor's own naming, e.g. General Purpose or Memory Optimized.",
        ),
        sa.Column(
            "series",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Hardware line and generation of the database, matching the series of the server it runs on, where known.",
        ),
        sa.Column(
            "server_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Reference to the underlying cloud server's identifier.",
        ),
        sa.Column(
            "vcpus",
            sa.Integer(),
            nullable=True,
            comment="Number of virtual CPU cores allocated to the database server instance.",
        ),
        sa.Column(
            "memory_amount",
            sa.Integer(),
            nullable=True,
            comment="Amount of RAM (MiB) provisioned for the instance.",
        ),
        sa.Column(
            "engine",
            _enum("databaseengine", ("POSTGRESQL",)),
            nullable=True,
            comment="Managed database engine running on the instance.",
        ),
        sa.Column(
            "wire_protocol",
            _enum("databasewireprotocol", ("POSTGRESQL",)),
            nullable=True,
            comment="Network protocol used for client connections.",
        ),
        sa.Column(
            "engine_versions",
            json_type(),
            nullable=False,
            comment="Major database engine versions supported.",
        ),
        sa.Column(
            "auto_upgrade_versions",
            sa.Boolean(),
            nullable=True,
            comment="Auto-upgrade between minor database engine versions.",
        ),
        sa.Column(
            "ha",
            json_type(),
            nullable=False,
            comment="Ordered HA levels supported, highest tier first.",
        ),
        sa.Column(
            "ha_strategy",
            json_type(),
            nullable=False,
            comment="Ordered HA strategies supported, highest tier first.",
        ),
        sa.Column(
            "max_read_replicas",
            sa.Integer(),
            nullable=True,
            comment="Maximum number of read-only replica nodes supported to scale read workloads.",
        ),
        sa.Column(
            "custom_config",
            sa.Boolean(),
            nullable=True,
            comment="Whether database engine parameters/flags can be customized.",
        ),
        sa.Column(
            "custom_extensions",
            sa.Boolean(),
            nullable=True,
            comment="Support for custom database engine extensions/plugins.",
        ),
        sa.Column(
            "storage_size",
            sa.Integer(),
            nullable=True,
            comment="Bundled storage capacity included in the database (GB).",
        ),
        sa.Column(
            "storage_extra_min",
            sa.Integer(),
            nullable=True,
            comment="Minimum custom storage size (in GB) that can be attached to the instance.",
        ),
        sa.Column(
            "storage_extra_max",
            sa.Integer(),
            nullable=True,
            comment="Maximum storage limit (in GB) supported by the instance or storage tier.",
        ),
        sa.Column(
            "storage_extra_autosize",
            sa.Boolean(),
            nullable=True,
            comment="Whether storage capacity can automatically expand as disk usage grows.",
        ),
        sa.Column(
            "compatible_storage_ids",
            json_type(none_as_null=True),
            nullable=True,
            comment="List of database_storage_ids that can be attached to the database as extra storage.",
        ),
        sa.Column(
            "disk_encryption",
            sa.Boolean(),
            nullable=True,
            comment="Indicates whether underlying storage drives are encrypted at rest.",
        ),
        sa.Column(
            "scheduled_backups",
            sa.Boolean(),
            nullable=True,
            comment="Support for automated snapshot schedules and backup retention management.",
        ),
        sa.Column(
            "continuous_backups",
            sa.Integer(),
            nullable=True,
            comment="Maximum point-in-time recovery (PITR) log retention window expressed in days (0 if unsupported).",
        ),
        sa.Column(
            "connection_pool",
            sa.Boolean(),
            nullable=True,
            comment="Managed connection proxy support.",
        ),
        sa.Column(
            "system_monitoring",
            sa.Boolean(),
            nullable=True,
            comment="Availability of host-level CPU, RAM, and disk metrics dashboards.",
        ),
        sa.Column(
            "database_monitoring",
            sa.Boolean(),
            nullable=True,
            comment="Database engine performance insights (slow queries, locks, execution plans).",
        ),
        sa.Column(
            "autotuning_advice",
            sa.Boolean(),
            nullable=True,
            comment="Analyzes workload and generates actionable performance tuning advice.",
        ),
        sa.Column(
            "autotuning_apply",
            sa.Boolean(),
            nullable=True,
            comment="System automatically executes performance fixes (e.g., index creation, parameter tuning) without operator intervention.",
        ),
        sa.Column(
            "sla",
            sa.Float(),
            nullable=True,
            comment="Service level agreement as a percentage, e.g. 99.95.",
        ),
        sa.Column(
            "security_features",
            json_type(),
            nullable=False,
            comment="Security capabilities supported by DBaaS providers.",
        ),
        sa.Column(
            "status",
            _enum(
                "status",
                (
                    "ACTIVE",
                    "INACTIVE",
                    "PLANNED_FOR_RETIREMENT",
                    "RETIRED",
                    "ARCHIVED",
                ),
            ),
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


def get_table(table: str, is_scd: bool, with_new_column: bool = False) -> sa.Table:
    """Pre-v0.12.0 ``server`` / ``database`` (or SCD) schema (copy_from source).

    With ``with_new_column``, the post-upgrade schema, used by the SQL-only
    (offline) SQLite downgrade.
    """
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    table_name = scdize_suffix(table)
    id_column, insert_after = _TABLES[table]
    columns = list(
        _server_columns(json_type)
        if table == "server"
        else _database_columns(json_type)
    )
    if with_new_column:
        position = [c.name for c in columns].index(insert_after) + 1
        columns.insert(position, _new_column())
    primary_keys = ("vendor_id", id_column) + (("observed_at",) if is_scd else ())
    foreign_keys = (
        ()
        if is_scd
        else (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_vendor"),
            ),
        )
    )
    model_name = "Server" if table == "server" else "Database"
    comment = "Server types." if table == "server" else "Managed database SKUs."
    return sa.Table(
        table_name,
        sa.MetaData(),
        *columns,
        *foreign_keys,
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
        comment=f"SCD version of .tables.{model_name}." if is_scd else comment,
    )


def upgrade() -> None:
    is_scd = is_scd_migration()
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd
    for table, (_, insert_after) in _TABLES.items():
        table_name = scdize_suffix(table)
        if do_recreate_tables:
            with op.batch_alter_table(
                table_name,
                schema=None,
                copy_from=get_table(table, is_scd),
                recreate="always",
            ) as batch_op:
                batch_op.add_column(_new_column(), insert_after=insert_after)
        else:
            op.add_column(table_name, _new_column())


def downgrade() -> None:
    # SQL-only SQLite downgrade cannot reflect the table: use the post-upgrade
    # schema; live downgrades reflect the actual table
    context = op.get_context()
    for table in _TABLES:
        copy_from = (
            get_table(table, is_scd_migration(), with_new_column=True)
            if context.dialect.name == "sqlite" and context.as_sql
            else None
        )
        with op.batch_alter_table(
            scdize_suffix(table), schema=None, copy_from=copy_from
        ) as batch_op:
            batch_op.drop_column("retirement_date")
