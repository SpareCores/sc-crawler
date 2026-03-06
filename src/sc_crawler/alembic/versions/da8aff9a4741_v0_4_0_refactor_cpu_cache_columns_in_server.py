"""v0.4.0 refactor cpu cache columns in server

Revision ID: da8aff9a4741
Revises: aeae56af8ca6
Create Date: 2026-03-06 11:18:02.480720

"""

from typing import Sequence, Union

import sqlalchemy as sa
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


def upgrade() -> None:
    server_table_name = scdize_suffix("server")
    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "cpu_l1i_cache",
                sa.Integer(),
                nullable=True,
                comment="L1i cache size (KiB).",
            )
        )
        batch_op.add_column(
            sa.Column(
                "cpu_l1i_cache_total",
                sa.Integer(),
                nullable=True,
                comment="Total L1i cache size (KiB) across all cores.",
            )
        )
        batch_op.add_column(
            sa.Column(
                "cpu_l1d_cache",
                sa.Integer(),
                nullable=True,
                comment="L1d cache size (KiB).",
            )
        )
        batch_op.add_column(
            sa.Column(
                "cpu_l1d_cache_total",
                sa.Integer(),
                nullable=True,
                comment="Total L1d cache size (KiB) across all cores.",
            )
        )
        batch_op.add_column(
            sa.Column(
                "cpu_l2_cache_total",
                sa.Integer(),
                nullable=True,
                comment="Total L2 cache size (KiB) across all cores.",
            )
        )
        batch_op.add_column(
            sa.Column(
                "cpu_l3_cache_total",
                sa.Integer(),
                nullable=True,
                comment="Total L3 cache size (KiB) across all cores.",
            )
        )

    # Old cpu_l1/l2_cache columns store total cache size in bytes across all cores.
    # New _total columns store total in KiB; per-core columns store per-core size in KiB.
    server_table = sa.table(
        server_table_name,
        sa.column("cpu_cores", sa.Integer()),
        sa.column("cpu_l1_cache", sa.Integer()),
        sa.column("cpu_l1i_cache", sa.Integer()),
        sa.column("cpu_l1i_cache_total", sa.Integer()),
        sa.column("cpu_l1d_cache", sa.Integer()),
        sa.column("cpu_l1d_cache_total", sa.Integer()),
        sa.column("cpu_l2_cache", sa.Integer()),
        sa.column("cpu_l2_cache_total", sa.Integer()),
        sa.column("cpu_l3_cache", sa.Integer()),
        sa.column("cpu_l3_cache_total", sa.Integer()),
    )
    op.execute(
        server_table.update()
        .where(server_table.c.cpu_l1_cache.isnot(None))
        .values(
            cpu_l1d_cache_total=server_table.c.cpu_l1_cache / 1024,
            cpu_l1i_cache_total=server_table.c.cpu_l1_cache / 1024,
        )
    )
    op.execute(
        server_table.update()
        .where(
            server_table.c.cpu_l1_cache.isnot(None),
            server_table.c.cpu_cores.isnot(None),
        )
        .values(
            cpu_l1d_cache=server_table.c.cpu_l1_cache / 1024 / server_table.c.cpu_cores,
            cpu_l1i_cache=server_table.c.cpu_l1_cache / 1024 / server_table.c.cpu_cores,
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
        .values(cpu_l3_cache_total=server_table.c.cpu_l3_cache / 1024)
        .values(cpu_l3_cache=None)
    )

    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        batch_op.drop_column("cpu_l1_cache")


def downgrade() -> None:
    server_table_name = scdize_suffix("server")
    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "cpu_l1_cache",
                sa.INTEGER(),
                nullable=True,
                comment="L1 cache size (bytes).",
            )
        )

    # Restore total bytes from _total KiB columns: total_bytes = total_KiB * 1024
    server_table = sa.table(
        server_table_name,
        sa.column("cpu_l1_cache", sa.Integer()),
        sa.column("cpu_l1d_cache_total", sa.Integer()),
        sa.column("cpu_l2_cache", sa.Integer()),
        sa.column("cpu_l2_cache_total", sa.Integer()),
        sa.column("cpu_l3_cache", sa.Integer()),
        sa.column("cpu_l3_cache_total", sa.Integer()),
    )
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

    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        batch_op.drop_column("cpu_l3_cache_total")
        batch_op.drop_column("cpu_l2_cache_total")
        batch_op.drop_column("cpu_l1d_cache_total")
        batch_op.drop_column("cpu_l1d_cache")
        batch_op.drop_column("cpu_l1i_cache_total")
        batch_op.drop_column("cpu_l1i_cache")
