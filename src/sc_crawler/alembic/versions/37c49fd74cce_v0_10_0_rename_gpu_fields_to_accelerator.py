"""v0.10.0 rename gpu fields to accelerator, add compatible storage ids and benchmark environment fields

Revision ID: 37c49fd74cce
Revises: b1c2d3e4f5a6
Create Date: 2026-10-05 18:34:57.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "37c49fd74cce"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def _foreign_keys(table_name: str, is_scd: bool) -> tuple:
    if is_scd:
        return ()
    return (
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendor.vendor_id"],
            name=op.f(f"fk_{table_name}_vendor_id_vendor"),
        ),
    )


_ACCELERATOR_TYPE_VALUES = ("GPU", "TPU")

# (old name, new name, old comment, new comment)
_RENAMED_SERVER_COLUMNS = (
    (
        "gpu_count",
        "accelerator_count",
        "Number of GPU accelerator(s).",
        "Number of accelerator(s), e.g. GPUs or TPUs.",
    ),
    (
        "gpu_memory_min",
        "accelerator_memory_min",
        "Memory (MiB) allocated to the lowest-end GPU accelerator.",
        "Memory (MiB) allocated to the lowest-end accelerator.",
    ),
    (
        "gpu_memory_total",
        "accelerator_memory_total",
        "Overall memory (MiB) allocated to all the GPU accelerator(s).",
        "Overall memory (MiB) allocated to all the accelerator(s).",
    ),
    (
        "gpu_manufacturer",
        "accelerator_manufacturer",
        "The manufacturer of the primary GPU accelerator, e.g. Nvidia or AMD.",
        "The manufacturer of the primary accelerator, e.g. Nvidia or AMD.",
    ),
    (
        "gpu_family",
        "accelerator_family",
        "The product family of the primary GPU accelerator, e.g. Turing.",
        "The product family of the primary accelerator, e.g. Turing.",
    ),
    (
        "gpu_model",
        "accelerator_model",
        "The model number of the primary GPU accelerator, e.g. Tesla T4.",
        "The model number of the primary accelerator, e.g. Tesla T4.",
    ),
    (
        "gpus",
        "accelerators",
        "JSON array of GPU accelerator details, including the manufacturer, name, and memory (MiB) of each GPU.",
        "JSON array of accelerator details, including the manufacturer, name, and memory (MiB) of each accelerator.",
    ),
)

_ACCELERATOR_TYPE_COMMENT = "The type of the primary accelerator, e.g. GPU or TPU."
_SERVER_COMPATIBLE_STORAGE_IDS_COMMENT = (
    "List of storage_ids that can be attached to the server as extra storage. "
    "An empty list means no extra storage can be attached, "
    "while null means all storage types of the vendor are compatible."
)
_DATABASE_COMPATIBLE_STORAGE_IDS_COMMENT = (
    "List of database_storage_ids that can be attached to the database as extra storage. "
    "An empty list means no extra storage can be attached, "
    "while null means all database storage types of the vendor are compatible."
)
_ENVIRONMENT_FIELDS_COMMENT = (
    "A dictionary of descriptions on the environment details recorded with the "
    'benchmark scores, e.g. {"kernel_version": "Linux kernel version of the server."}.'
)


def get_server_table(is_scd: bool) -> sa.Table:
    """Pre-v0.10.0 ``server`` / ``server_scd`` schema (copy_from source)."""
    table_name = scdize_suffix("server")
    primary_keys = (
        ("vendor_id", "server_id", "observed_at")
        if is_scd
        else ("vendor_id", "server_id")
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
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depending on the vendor and actual API endpoint.",
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
            _enum("cpuallocation", ("SHARED", "BURSTABLE", "DEDICATED")),
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
                ("ARM64", "ARM64_MAC", "I386", "X86_64", "X86_64_MAC"),
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
            comment="L2 cache size (byte).",
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
            comment="L3 cache size (byte).",
        ),
        sa.Column(
            "cpu_l3_cache_total",
            sa.Integer(),
            nullable=True,
            comment="Total L3 cache size (KiB) across all cores.",
        ),
        sa.Column(
            "cpu_flags",
            sa.JSON(),
            nullable=False,
            comment="CPU features/flags.",
        ),
        sa.Column(
            "cpus",
            sa.JSON(),
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
            _enum("ddrgeneration", ("DDR3", "DDR4", "DDR5")),
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
            sa.Float(),
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
            _enum("storagetype", ("HDD", "SSD", "NVME_SSD", "NETWORK")),
            nullable=True,
            comment="Primary disk type, e.g. HDD, SSD, NVMe SSD, or network).",
        ),
        sa.Column(
            "storages",
            sa.JSON(),
            nullable=False,
            comment="JSON array of disks attached to the server, including the size (GB) and type of each disk.",
        ),
        sa.Column(
            "network_speed_baseline",
            sa.Float(),
            nullable=True,
            comment="The baseline network performance (Gbps) of the network card.",
        ),
        sa.Column(
            "network_speed_max",
            sa.Float(),
            nullable=True,
            comment="The maximum network performance (Gbps) of the network card.",
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
                "status", ("ACTIVE", "INACTIVE", "PLANNED_FOR_RETIREMENT", "RETIRED")
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
        *_foreign_keys(table_name, is_scd),
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Server." if is_scd else "Server types.",
    )


def get_database_table(is_scd: bool) -> sa.Table:
    """Pre-v0.10.0 ``database`` / ``database_scd`` schema (copy_from source)."""
    is_postgresql = op.get_context().dialect.name == "postgresql"
    table_name = scdize_suffix("database")
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    primary_keys = (
        ("vendor_id", "database_id", "observed_at")
        if is_scd
        else ("vendor_id", "database_id")
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
            json_type(),
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
            comment="Hardware family or class classification.",
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
                "status", ("ACTIVE", "INACTIVE", "PLANNED_FOR_RETIREMENT", "RETIRED")
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
        *_foreign_keys(table_name, is_scd),
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Database."
        if is_scd
        else "Managed database SKUs.",
    )


def get_benchmark_table(is_scd: bool) -> sa.Table:
    """Pre-v0.10.0 ``benchmark`` / ``benchmark_scd`` schema (copy_from source)."""
    is_postgresql = op.get_context().dialect.name == "postgresql"
    table_name = scdize_suffix("benchmark")
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    primary_keys = ("benchmark_id", "observed_at") if is_scd else ("benchmark_id",)
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
            "category",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Category of the resource.",
        ),
        sa.Column(
            "source",
            json_type(),
            # added as nullable in v0.8.0 and never altered since
            nullable=True,
            comment="How the benchmark score is produced. A discriminated object keyed by 'kind': 'measured' (directly observed), 'extrapolated' (derived from this server's own measurements; carries 'derived_from' + 'note'), or 'compound' (aggregated across component benchmarks; carries 'aggregation', 'normalization', and the 'components' recipe).",
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
            "note",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional caveat/comment on how to interpret the metric, surfaced as a warning/info badge (e.g. limited scaling on high vCPU counts, or independence from vCPU count). Null when there is nothing to flag.",
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
            comment="The name of measurement recorded in the benchmark.",
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
            _enum(
                "status", ("ACTIVE", "INACTIVE", "PLANNED_FOR_RETIREMENT", "RETIRED")
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
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Benchmark."
        if is_scd
        else "Benchmark scenario definitions.",
    )


def upgrade() -> None:
    is_scd = is_scd_migration()
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    server_table_name = scdize_suffix("server")
    database_table_name = scdize_suffix("database")
    benchmark_table_name = scdize_suffix("benchmark")
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd

    if is_postgresql:
        sa.Enum(*_ACCELERATOR_TYPE_VALUES, name="acceleratortype").create(
            op.get_bind(), checkfirst=True
        )

    accelerator_type_column = sa.Column(
        "accelerator_type",
        _enum("acceleratortype", _ACCELERATOR_TYPE_VALUES),
        nullable=True,
        comment=_ACCELERATOR_TYPE_COMMENT,
    )
    # JSON columns of the server table are plain JSON (not JSONB) in PostgreSQL
    server_compatible_storage_ids_column = sa.Column(
        "compatible_storage_ids",
        sa.JSON(),
        nullable=True,
        comment=_SERVER_COMPATIBLE_STORAGE_IDS_COMMENT,
    )
    database_compatible_storage_ids_column = sa.Column(
        "compatible_storage_ids",
        json_type(),
        nullable=True,
        comment=_DATABASE_COMPATIBLE_STORAGE_IDS_COMMENT,
    )
    environment_fields_column = sa.Column(
        "environment_fields",
        json_type(),
        nullable=False,
        server_default="{}",
        comment=_ENVIRONMENT_FIELDS_COMMENT,
    )

    if do_recreate_tables:
        # new columns are positioned relative to the old (pre-rename) column names
        with op.batch_alter_table(
            server_table_name,
            schema=None,
            copy_from=get_server_table(is_scd),
            recreate="always",
        ) as batch_op:
            batch_op.add_column(
                accelerator_type_column, insert_after="gpu_memory_total"
            )
            batch_op.add_column(
                server_compatible_storage_ids_column, insert_after="storages"
            )
            for old_name, new_name, _, comment in _RENAMED_SERVER_COLUMNS:
                batch_op.alter_column(
                    old_name, new_column_name=new_name, comment=comment
                )
        with op.batch_alter_table(
            database_table_name,
            schema=None,
            copy_from=get_database_table(is_scd),
            recreate="always",
        ) as batch_op:
            batch_op.add_column(
                database_compatible_storage_ids_column,
                insert_after="storage_extra_autosize",
            )
        with op.batch_alter_table(
            benchmark_table_name,
            schema=None,
            copy_from=get_benchmark_table(is_scd),
            recreate="always",
        ) as batch_op:
            batch_op.add_column(environment_fields_column, insert_after="config_fields")
    else:
        for old_name, new_name, _, comment in _RENAMED_SERVER_COLUMNS:
            op.alter_column(
                server_table_name,
                old_name,
                new_column_name=new_name,
                comment=comment,
            )
        op.add_column(server_table_name, accelerator_type_column)
        op.add_column(server_table_name, server_compatible_storage_ids_column)
        op.add_column(database_table_name, database_compatible_storage_ids_column)
        op.add_column(benchmark_table_name, environment_fields_column)

    # SQLite cannot DROP DEFAULT via ALTER COLUMN; leave the migration default there.
    if is_postgresql:
        op.alter_column(
            benchmark_table_name,
            "environment_fields",
            server_default=None,
            existing_nullable=False,
        )


def downgrade() -> None:
    is_postgresql = op.get_context().dialect.name == "postgresql"
    server_table_name = scdize_suffix("server")
    database_table_name = scdize_suffix("database")
    benchmark_table_name = scdize_suffix("benchmark")

    with op.batch_alter_table(benchmark_table_name, schema=None) as batch_op:
        batch_op.drop_column("environment_fields")
    with op.batch_alter_table(database_table_name, schema=None) as batch_op:
        batch_op.drop_column("compatible_storage_ids")
    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        batch_op.drop_column("compatible_storage_ids")
        batch_op.drop_column("accelerator_type")
        for old_name, new_name, comment, _ in _RENAMED_SERVER_COLUMNS:
            batch_op.alter_column(new_name, new_column_name=old_name, comment=comment)

    if is_postgresql:
        sa.Enum(name="acceleratortype").drop(op.get_bind(), checkfirst=True)
