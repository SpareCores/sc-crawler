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


def scdize_suffix(table_name: str) -> str:
    if op.get_context().config.attributes.get("scd"):
        return table_name + "_scd"
    return table_name


# need to provide the table schema for offline mode support
server_primary_key = (
    ("vendor_id", "server_id", "observed_at")
    if op.get_context().config.attributes.get("scd")
    else (
        "vendor_id",
        "server_id",
    )
)
server_foreign_key = (
    (
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            [f"{scdize_suffix('vendor')}.vendor_id"],
            name=op.f(
                f"fk_{scdize_suffix('server')}_vendor_id_{scdize_suffix('vendor')}"
            ),
        ),
    )
    if not op.get_context().config.attributes.get("scd")
    else ()
)
server_table = sa.Table(
    scdize_suffix("server"),
    sa.MetaData(),
    sa.Column("vendor_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("server_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("api_reference", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("family", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("vcpus", sa.Integer(), nullable=False),
    sa.Column("hypervisor", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column(
        "cpu_allocation",
        sa.Enum("SHARED", "BURSTABLE", "DEDICATED", name="cpuallocation"),
        nullable=False,
    ),
    sa.Column("cpu_cores", sa.Integer(), nullable=True),
    sa.Column("cpu_speed", sa.Float(), nullable=True),
    sa.Column(
        "cpu_architecture",
        sa.Enum(
            "ARM64", "ARM64_MAC", "I386", "X86_64", "X86_64_MAC", name="cpuarchitecture"
        ),
        nullable=False,
    ),
    sa.Column("cpu_manufacturer", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("cpu_family", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("cpu_model", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("cpu_l1_cache", sa.Integer(), nullable=True),
    sa.Column("cpu_l2_cache", sa.Integer(), nullable=True),
    sa.Column("cpu_l3_cache", sa.Integer(), nullable=True),
    sa.Column("cpu_flags", sa.JSON(), nullable=False),
    sa.Column("cpus", sa.JSON(), nullable=False),
    sa.Column("memory_amount", sa.Integer(), nullable=False),
    sa.Column(
        "memory_generation",
        sa.Enum("DDR3", "DDR4", "DDR5", name="ddrgeneration"),
        nullable=True,
    ),
    sa.Column("memory_speed", sa.Integer(), nullable=True),
    sa.Column("memory_ecc", sa.Boolean(), nullable=True),
    sa.Column("gpu_count", sa.Integer(), nullable=False),
    sa.Column("gpu_memory_min", sa.Integer(), nullable=True),
    sa.Column("gpu_memory_total", sa.Integer(), nullable=True),
    sa.Column("gpu_manufacturer", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("gpu_family", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("gpu_model", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("gpus", sa.JSON(), nullable=False),
    sa.Column("storage_size", sa.Integer(), nullable=False),
    sa.Column(
        "storage_type",
        sa.Enum("HDD", "SSD", "NVME_SSD", "NETWORK", name="storagetype"),
        nullable=True,
    ),
    sa.Column("storages", sa.JSON(), nullable=False),
    sa.Column("network_speed", sa.Float(), nullable=True),
    sa.Column("inbound_traffic", sa.Float(), nullable=False),
    sa.Column("outbound_traffic", sa.Float(), nullable=False),
    sa.Column("ipv4", sa.Integer(), nullable=False),
    sa.Column("status", sa.Enum("ACTIVE", "INACTIVE", name="status"), nullable=False),
    sa.Column("observed_at", sa.DateTime(), nullable=False),
    *server_foreign_key,
    sa.PrimaryKeyConstraint(*server_primary_key),
)


def upgrade() -> None:
    server_table_name = scdize_suffix("server")
    do_recreate_tables = (
        op.get_context().dialect.name == "sqlite"
    ) or op.get_context().config.attributes.get("scd")

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
            server_table_name, schema=None, copy_from=server_table, recreate="always"
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

    for col_name, _, _ in new_columns:
        server_table.append_column(sa.Column(col_name, sa.Integer()))

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
            cpu_l3_cache_total=server_table.c.cpu_l3_cache / 1024, cpu_l3_cache=None
        )
    )

    if do_recreate_tables:
        with op.batch_alter_table(server_table_name, schema=None) as batch_op:
            batch_op.drop_column("cpu_l1_cache")
    else:
        op.drop_column(server_table_name, "cpu_l1_cache")


def downgrade() -> None:
    server_table_name = scdize_suffix("server")
    do_recreate_tables = (
        op.get_context().dialect.name == "sqlite"
    ) or op.get_context().config.attributes.get("scd")

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
            server_table_name, schema=None, copy_from=server_table, recreate="always"
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "cpu_l1_cache",
                    sa.INTEGER(),
                    nullable=True,
                    comment="L1 cache size (bytes).",
                ),
                insert_after="cpu_model",
            )
    else:
        op.add_column(
            server_table_name,
            sa.Column(
                "cpu_l1_cache",
                sa.INTEGER(),
                nullable=True,
                comment="L1 cache size (bytes).",
            ),
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
    if do_recreate_tables:
        with op.batch_alter_table(server_table_name, schema=None) as batch_op:
            for col in drop_columns:
                batch_op.drop_column(col)
    else:
        for col in drop_columns:
            op.drop_column(server_table_name, col)
