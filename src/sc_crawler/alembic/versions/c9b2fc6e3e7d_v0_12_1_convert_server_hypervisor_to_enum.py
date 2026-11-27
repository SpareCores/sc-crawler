"""v0.12.1 convert server hypervisor to enum

Revision ID: c9b2fc6e3e7d
Revises: 67f053fde65f
Create Date: 2026-11-27 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9b2fc6e3e7d"
down_revision: Union[str, None] = "67f053fde65f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_VALUES = ("KVM", "XEN", "NITRO", "HYPER_V", "BARE_METAL")

_OLD_COMMENT = "Hypervisor of the virtual server, e.g. Xen, KVM, Nitro or Dedicated."
_NEW_COMMENT = (
    "Hypervisor of the server, e.g. KVM, Xen, Nitro or Hyper-V, "
    "or Bare metal for servers without a hypervisor. Empty when not known."
)

# free-text values stored before v0.12.1 -> enum names, other values are dropped;
# bare metal servers are set by the next inventory refresh
_UPGRADE_VALUES = {
    "KVM": "KVM",
    "QEMU": "KVM",
    "xen": "XEN",
    "nitro": "NITRO",
    "Microsoft Hyper-V": "HYPER_V",
}
# BARE_METAL was stored as NULL before v0.12.1
_DOWNGRADE_VALUES = {
    "KVM": "KVM",
    "XEN": "xen",
    "NITRO": "nitro",
    "HYPER_V": "Microsoft Hyper-V",
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


def _server_columns(json_type, hypervisor_type, hypervisor_comment: str) -> tuple:
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
            hypervisor_type,
            nullable=True,
            comment=hypervisor_comment,
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
            "retirement_date",
            sa.Date(),
            nullable=True,
            comment="Retirement date announced by the vendor for PLANNED_FOR_RETIREMENT and RETIRED records: the end of support (shutdown) if published, otherwise the end of sale. Empty when not announced or not known.",
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


def get_table(is_scd: bool, upgraded: bool) -> sa.Table:
    """SQLite ``server`` (or SCD) schema before (or with ``upgraded``, after) v0.12.1."""
    table_name = scdize_suffix("server")
    columns = _server_columns(
        sa.JSON,
        _enum("hypervisor", _VALUES)
        if upgraded
        else sqlmodel.sql.sqltypes.AutoString(),
        _NEW_COMMENT if upgraded else _OLD_COMMENT,
    )
    primary_keys = ("vendor_id", "server_id") + (("observed_at",) if is_scd else ())
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
    return sa.Table(
        table_name,
        sa.MetaData(),
        *columns,
        *foreign_keys,
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Server." if is_scd else "Server types.",
    )


def _remap_values(table_name: str, mapping: dict[str, str]) -> None:
    table = sa.table(table_name, sa.column("hypervisor", sa.String))
    op.execute(
        table.update().values(
            hypervisor=sa.case(mapping, value=table.c.hypervisor, else_=None)
        )
    )


def upgrade() -> None:
    is_scd = is_scd_migration()
    table_name = scdize_suffix("server")
    _remap_values(table_name, _UPGRADE_VALUES)
    if op.get_context().dialect.name == "postgresql":
        sa.Enum(*_VALUES, name="hypervisor").create(op.get_bind(), checkfirst=True)
        op.alter_column(
            table_name,
            "hypervisor",
            type_=_enum("hypervisor", _VALUES),
            existing_type=sqlmodel.sql.sqltypes.AutoString(),
            existing_nullable=True,
            comment=_NEW_COMMENT,
            existing_comment=_OLD_COMMENT,
            postgresql_using="hypervisor::hypervisor",
        )
    else:
        with op.batch_alter_table(
            table_name,
            schema=None,
            copy_from=get_table(is_scd, upgraded=False),
            recreate="always",
        ) as batch_op:
            batch_op.alter_column(
                "hypervisor",
                type_=_enum("hypervisor", _VALUES),
                existing_type=sqlmodel.sql.sqltypes.AutoString(),
                existing_nullable=True,
                comment=_NEW_COMMENT,
                existing_comment=_OLD_COMMENT,
            )


def downgrade() -> None:
    is_scd = is_scd_migration()
    table_name = scdize_suffix("server")
    if op.get_context().dialect.name == "postgresql":
        op.alter_column(
            table_name,
            "hypervisor",
            type_=sqlmodel.sql.sqltypes.AutoString(),
            existing_type=_enum("hypervisor", _VALUES),
            existing_nullable=True,
            comment=_OLD_COMMENT,
            existing_comment=_NEW_COMMENT,
            postgresql_using="hypervisor::text",
        )
        sa.Enum(name="hypervisor").drop(op.get_bind(), checkfirst=True)
    else:
        with op.batch_alter_table(
            table_name,
            schema=None,
            copy_from=get_table(is_scd, upgraded=True),
            recreate="always",
        ) as batch_op:
            batch_op.alter_column(
                "hypervisor",
                type_=sqlmodel.sql.sqltypes.AutoString(),
                existing_type=_enum("hypervisor", _VALUES),
                existing_nullable=True,
                comment=_OLD_COMMENT,
                existing_comment=_NEW_COMMENT,
            )
    _remap_values(table_name, _DOWNGRADE_VALUES)
