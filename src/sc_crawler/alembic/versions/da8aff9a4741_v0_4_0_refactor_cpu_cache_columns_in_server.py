"""v0.4.0 refactor cpu cache columns in server

Revision ID: da8aff9a4741
Revises: aeae56af8ca6
Create Date: 2026-03-06 11:18:02.480720

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

from sc_crawler.alembic.create_tables import (
    create_server_table,
)

# revision identifiers, used by Alembic.
revision: str = "da8aff9a4741"
down_revision: Union[str, None] = "aeae56af8ca6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return op.get_context().config.attributes.get("scd")


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def get_server_table_v034(scd: bool) -> sa.Table:
    """Return server table as it exists after aeae56af8ca6 (v0.3.4)."""
    table = create_server_table(scd)
    gpu_col = table.c.gpu_count
    new_col = sa.Column(
        "gpu_count",
        sa.Float(),
        nullable=gpu_col.nullable,
        comment=gpu_col.comment,
    )
    table._columns.replace(new_col)
    return table


def upgrade() -> None:
    server_table_name = scdize_suffix("server")
    server_table = get_server_table_v034(is_scd_migration())
    do_recreate_tables = (
        op.get_context().dialect.name == "sqlite"
    ) or is_scd_migration()

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
        # Only convert if BigInteger (i.e. downgrade was run before re-upgrading)
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        cols = {c["name"]: c["type"] for c in inspector.get_columns(server_table_name)}
        if isinstance(cols.get("cpu_l2_cache"), sa.BigInteger):
            op.alter_column(
                server_table_name,
                "cpu_l2_cache",
                existing_type=sa.BigInteger(),
                type_=sa.Integer(),
            )
        if isinstance(cols.get("cpu_l3_cache"), sa.BigInteger):
            op.alter_column(
                server_table_name,
                "cpu_l3_cache",
                existing_type=sa.BigInteger(),
                type_=sa.Integer(),
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
        with op.batch_alter_table(
            server_table_name, schema=None, copy_from=server_table
        ) as batch_op:
            batch_op.drop_column("cpu_l1_cache")
    else:
        op.drop_column(server_table_name, "cpu_l1_cache")


def downgrade() -> None:
    server_table_name = scdize_suffix("server")
    server_table = get_server_table_v034(is_scd_migration())
    do_recreate_tables = (
        op.get_context().dialect.name == "sqlite"
    ) or is_scd_migration()

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
    if do_recreate_tables:
        with op.batch_alter_table(server_table_name, schema=None) as batch_op:
            for col in drop_columns:
                batch_op.drop_column(col)
    else:
        for col in drop_columns:
            op.drop_column(server_table_name, col)
