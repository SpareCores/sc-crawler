"""v0.5.3 add new server fields

Revision ID: f0273cb124f6
Revises: 055e00abdcb5
Create Date: 2026-05-22 11:21:10.600701

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0273cb124f6"
down_revision: Union[str, None] = "055e00abdcb5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def get_server_table(is_scd: bool) -> sa.Table:
    is_postgresql = op.get_context().dialect.name == "postgresql"
    table_name = scdize_suffix("server")
    primary_key = (
        ("vendor_id", "server_id", "observed_at")
        if is_scd
        else ("vendor_id", "server_id")
    )
    foreign_key = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
                name=op.f("fk_server_vendor_id_vendor"),
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
            sa.dialects.postgresql.ENUM(
                "SHARED",
                "BURSTABLE",
                "DEDICATED",
                name="cpuallocation",
                create_type=False,
            )
            if is_postgresql
            else sa.Enum(
                "SHARED",
                "BURSTABLE",
                "DEDICATED",
                name="cpuallocation",
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
            sa.dialects.postgresql.ENUM(
                "ARM64",
                "ARM64_MAC",
                "I386",
                "X86_64",
                "X86_64_MAC",
                name="cpuarchitecture",
                create_type=False,
            )
            if is_postgresql
            else sa.Enum(
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
            "cpu_l2_cache", sa.Integer(), nullable=True, comment="L2 cache size (KiB)."
        ),
        sa.Column(
            "cpu_l2_cache_total",
            sa.Integer(),
            nullable=True,
            comment="Total L2 cache size (KiB) across all cores.",
        ),
        sa.Column(
            "cpu_l3_cache", sa.Integer(), nullable=True, comment="L3 cache size (KiB)."
        ),
        sa.Column(
            "cpu_l3_cache_total",
            sa.Integer(),
            nullable=True,
            comment="Total L3 cache size (KiB) across all cores.",
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
            sa.dialects.postgresql.ENUM(
                "DDR3", "DDR4", "DDR5", name="ddrgeneration", create_type=False
            )
            if is_postgresql
            else sa.Enum(
                "DDR3",
                "DDR4",
                "DDR5",
                name="ddrgeneration",
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
            sa.dialects.postgresql.ENUM(
                "HDD",
                "SSD",
                "NVME_SSD",
                "NETWORK",
                name="storagetype",
                create_type=False,
            )
            if is_postgresql
            else sa.Enum(
                "HDD",
                "SSD",
                "NVME_SSD",
                "NETWORK",
                name="storagetype",
            ),
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
            sa.dialects.postgresql.ENUM(
                "ACTIVE", "INACTIVE", name="status", create_type=False
            )
            if is_postgresql
            else sa.Enum(
                "ACTIVE",
                "INACTIVE",
                name="status",
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
        *foreign_key,
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Server." if is_scd else "Server types.",
    )


def upgrade() -> None:
    is_scd = is_scd_migration()
    is_postgresql = op.get_context().dialect.name == "postgresql"
    server_table_name = scdize_suffix("server")
    server_table = get_server_table(is_scd)
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd
    if do_recreate_tables:
        with op.batch_alter_table(
            server_table_name,
            schema=None,
            copy_from=server_table,
            recreate="always",
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "ecpus",
                    sa.Float(),
                    nullable=True,
                    comment='The effective "real-world" core count, calculated by dividing the maximum multi-core SCore by the single-core SCore.',
                ),
                insert_after="cpus",
            )
            batch_op.add_column(
                sa.Column(
                    "scalability",
                    sa.Float(),
                    nullable=True,
                    comment="Measures how efficiently the server scales from a single core performance to using multiple cores. A score of 100% means perfect linear scaling with zero performance loss.",
                ),
                insert_after="ecpus",
            )
            batch_op.add_column(
                sa.Column(
                    "hw_virt",
                    sa.Boolean(),
                    nullable=True,
                    comment="If nested hardware virtualization is exposed to the guest.",
                ),
                insert_after="scalability",
            )
            batch_op.alter_column(
                "memory_amount",
                comment="RAM amount (MiB) reported by the vendor.",
            )
            batch_op.add_column(
                sa.Column(
                    "memory_amount_actual",
                    sa.Integer(),
                    nullable=True,
                    comment="Actual RAM amount (MiB) reported by lstopo or similar tool.",
                ),
                insert_after="memory_amount",
            )
            batch_op.add_column(
                sa.Column(
                    "network_speed_baseline",
                    sa.Float(),
                    nullable=True,
                    comment="The baseline network performance (Gbps) of the network card.",
                )
            )
            batch_op.add_column(
                sa.Column(
                    "network_speed_max",
                    sa.Float(),
                    nullable=True,
                    comment="The maximum network performance (Gbps) of the network card.",
                )
            )
            batch_op.add_column(
                sa.Column(
                    "network_storage_speed_baseline",
                    sa.Float(),
                    nullable=True,
                    comment="The baseline network-attached storage performance (Gbps) of the network card.",
                )
            )
            batch_op.add_column(
                sa.Column(
                    "network_storage_speed_max",
                    sa.Float(),
                    nullable=True,
                    comment="The maximum network-attached storage performance (Gbps) of the network card.",
                )
            )
            batch_op.drop_column("network_speed")


def downgrade() -> None:
    with op.batch_alter_table("server", schema=None) as batch_op:
        batch_op.add_column(sa.Column("network_speed", sa.FLOAT(), nullable=True))
        batch_op.drop_column("network_storage_speed_max")
        batch_op.drop_column("network_storage_speed_baseline")
        batch_op.drop_column("network_speed_max")
        batch_op.drop_column("network_speed_baseline")
        batch_op.drop_column("memory_amount_actual")
        batch_op.drop_column("hw_virt")
        batch_op.drop_column("scalability")
        batch_op.drop_column("ecpus")
