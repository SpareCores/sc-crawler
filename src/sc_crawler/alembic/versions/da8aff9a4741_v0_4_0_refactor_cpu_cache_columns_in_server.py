"""v0.4.0 refactor cpu cache columns in server

Revision ID: da8aff9a4741
Revises: aeae56af8ca6
Create Date: 2026-03-06 11:18:02.480720

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "da8aff9a4741"
down_revision: Union[str, None] = "aeae56af8ca6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def _insert_column_after(table: sa.Table, new_col: sa.Column, after: str):
    """Insert a column into a Table's column collection after the named column."""
    cols = list(table.c)
    idx = next(i for i, c in enumerate(cols) if c.name == after) + 1
    tail = cols[idx:]
    for c in tail:
        table._columns.remove(c)
    table.append_column(new_col)
    for c in tail:
        table.append_column(c)


def get_server_table(is_scd: bool) -> sa.Table:
    is_postgresql = op.get_context().dialect.name == "postgresql"
    server_table = sa.Table(
        "server",
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
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendor.vendor_id"],
            name=op.f("fk_server_vendor_id_vendor"),
        ),
        sa.PrimaryKeyConstraint("vendor_id", "server_id", name=op.f("pk_server")),
        comment="Server types.",
    )
    server_scd_table = sa.Table(
        "server_scd",
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
            sa.dialects.postgresql.ENUM(
                "ACTIVE", "INACTIVE", name="status", create_type=False
            )
            if is_postgresql
            else sa.Enum("ACTIVE", "INACTIVE", name="status"),
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
            "vendor_id", "server_id", "observed_at", name=op.f("pk_server_scd")
        ),
        comment="SCD version of .tables.Server.",
    )
    return server_scd_table if is_scd else server_table


def upgrade() -> None:
    is_scd = is_scd_migration()
    server_table_name = scdize_suffix("server")
    server_table = get_server_table(is_scd)
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd

    new_columns = [
        ("cpu_l1d_cache", "L1 data cache size (KiB).", "cpu_model"),
        (
            "cpu_l1d_cache_total",
            "Total L1 data cache size (KiB) across all cores.",
            "cpu_l1d_cache",
        ),
        ("cpu_l1i_cache", "L1 instruction cache size (KiB).", "cpu_l1d_cache_total"),
        (
            "cpu_l1i_cache_total",
            "Total L1 instruction cache size (KiB) across all cores.",
            "cpu_l1i_cache",
        ),
        (
            "cpu_l2_cache_total",
            "Total L2 cache size (KiB) across all cores.",
            "cpu_l2_cache",
        ),
        (
            "cpu_l3_cache_total",
            "Total L3 cache size (KiB) across all cores.",
            "cpu_l3_cache",
        ),
    ]

    if do_recreate_tables:
        with op.batch_alter_table(
            server_table,
            schema=None,
            copy_from=server_table,
            recreate="always",
        ) as batch_op:
            for col_name, comment, after in new_columns:
                batch_op.add_column(
                    sa.Column(col_name, sa.Integer(), nullable=True, comment=comment),
                    insert_after=after,
                )
    else:
        for col_name, comment, _ in new_columns:
            op.add_column(
                server_table_name,
                sa.Column(col_name, sa.Integer(), nullable=True, comment=comment),
            )

    for col_name, comment, after in new_columns:
        _insert_column_after(
            server_table,
            sa.Column(col_name, sa.Integer(), nullable=True, comment=comment),
            after,
        )

    # Old cpu_l1/l2/l3_cache columns store total cache size in bytes across all cores.
    # New _total columns store total in KiB; per-core columns store per-core size in KiB.
    op.execute(
        server_table.update()
        .where(server_table.c.cpu_l1_cache.isnot(None))
        .values(cpu_l1d_cache_total=server_table.c.cpu_l1_cache / 1024)
    )
    op.execute(
        server_table.update()
        .where(
            server_table.c.cpu_l1_cache.isnot(None),
            server_table.c.cpu_cores.isnot(None),
        )
        .values(
            cpu_l1d_cache=server_table.c.cpu_l1_cache / 1024 / server_table.c.cpu_cores
        )
    )
    op.execute(
        server_table.update()
        .where(server_table.c.cpu_l2_cache.isnot(None))
        .values(cpu_l2_cache_total=server_table.c.cpu_l2_cache / 1024)
    )
    op.execute(
        server_table.update()
        .where(
            server_table.c.cpu_l2_cache.isnot(None),
            server_table.c.cpu_cores.isnot(None),
        )
        .values(
            cpu_l2_cache=server_table.c.cpu_l2_cache / 1024 / server_table.c.cpu_cores
        )
    )
    # L3 cache is usually shared across all cores: populate total only, leave per-core null.
    op.execute(
        server_table.update()
        .where(server_table.c.cpu_l3_cache.isnot(None))
        .values(
            cpu_l3_cache_total=server_table.c.cpu_l3_cache / 1024,
            cpu_l3_cache=None,
        )
    )

    if do_recreate_tables:
        with op.batch_alter_table(
            server_table_name, schema=None, copy_from=server_table
        ) as batch_op:
            batch_op.drop_column("cpu_l1_cache")
    else:
        op.drop_column(server_table_name, "cpu_l1_cache")


def downgrade() -> None:
    is_scd = is_scd_migration()
    server_table_name = scdize_suffix("server")
    server_table = get_server_table(is_scd)
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd

    for col_name in [
        "cpu_l1d_cache",
        "cpu_l1d_cache_total",
        "cpu_l1i_cache",
        "cpu_l1i_cache_total",
        "cpu_l2_cache_total",
        "cpu_l3_cache_total",
    ]:
        server_table.append_column(sa.Column(col_name, sa.Integer()))

    if do_recreate_tables:
        with op.batch_alter_table(
            server_table_name,
            schema=None,
            copy_from=server_table,
            recreate="always",
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "cpu_l1_cache",
                    sa.BigInteger(),
                    nullable=True,
                    comment="L1 cache size (bytes).",
                ),
                insert_after="cpu_model",
            )
            batch_op.alter_column(
                "cpu_l2_cache", existing_type=sa.Integer(), type_=sa.BigInteger()
            )
            batch_op.alter_column(
                "cpu_l3_cache", existing_type=sa.Integer(), type_=sa.BigInteger()
            )
    else:
        op.add_column(
            server_table_name,
            sa.Column(
                "cpu_l1_cache",
                sa.BigInteger(),
                nullable=True,
                comment="L1 cache size (bytes).",
            ),
        )
        # these columns remain BigIntegers after this downgrade in this case,
        # regardless of whether this migration's upgrade has run or not
        op.alter_column(
            server_table_name,
            "cpu_l2_cache",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
        )
        op.alter_column(
            server_table_name,
            "cpu_l3_cache",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
        )

    # Restore total bytes from _total KiB columns: total_bytes = total_KiB * 1024
    op.execute(
        server_table.update()
        .where(server_table.c.cpu_l1d_cache_total.isnot(None))
        .values(cpu_l1_cache=server_table.c.cpu_l1d_cache_total * 1024)
    )
    op.execute(
        server_table.update()
        .where(server_table.c.cpu_l2_cache_total.isnot(None))
        .values(cpu_l2_cache=server_table.c.cpu_l2_cache_total * 1024)
    )
    op.execute(
        server_table.update()
        .where(server_table.c.cpu_l3_cache_total.isnot(None))
        .values(cpu_l3_cache=server_table.c.cpu_l3_cache_total * 1024)
    )

    drop_columns = [
        "cpu_l1d_cache",
        "cpu_l1d_cache_total",
        "cpu_l1i_cache",
        "cpu_l1i_cache_total",
        "cpu_l2_cache_total",
        "cpu_l3_cache_total",
    ]

    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        for col in drop_columns:
            batch_op.drop_column(col)
