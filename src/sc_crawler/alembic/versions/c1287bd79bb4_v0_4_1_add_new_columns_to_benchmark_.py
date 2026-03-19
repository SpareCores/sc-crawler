"""v0.4.1 add new columns to benchmark_score

Revision ID: c1287bd79bb4
Revises: da8aff9a4741
Create Date: 2026-03-19 16:37:16.708986

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1287bd79bb4"
down_revision: Union[str, None] = "da8aff9a4741"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def get_benchmark_score_table(is_scd: bool) -> sa.Table:
    is_postgresql = op.get_context().dialect.name == "postgresql"
    table_name = scdize_suffix("benchmark_score")
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    primary_keys = (
        ("server_id", "benchmark_id", "config", "observed_at", "vendor_id")
        if is_scd
        else ("vendor_id", "server_id", "benchmark_id", "config")
    )
    foreign_keys = (
        (
            sa.ForeignKeyConstraint(
                ["benchmark_id"],
                ["benchmark.benchmark_id"],
                name=op.f("fk_benchmark_score_benchmark_id_benchmark"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "server_id"],
                ["server.vendor_id", "server.server_id"],
                name=op.f("fk_benchmark_score_vendor_id_server"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
                name=op.f("fk_benchmark_score_vendor_id_vendor"),
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
        *foreign_keys,
        sa.PrimaryKeyConstraint(
            *primary_keys,
            name=op.f(f"pk_{table_name}"),
        ),
        comment="SCD version of .tables.BenchmarkScore."
        if is_scd
        else "Results of running Benchmark scenarios on Servers.",
    )


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


def upgrade() -> None:
    is_scd = is_scd_migration()
    benchmark_score_table_name = scdize_suffix("benchmark_score")
    benchmark_score_table = get_benchmark_score_table(is_scd)
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd
    if do_recreate_tables:
        with op.batch_alter_table(
            benchmark_score_table_name,
            schema=None,
            copy_from=benchmark_score_table,
            recreate="always",
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "framework_version",
                    sqlmodel.sql.sqltypes.AutoString(),
                    nullable=True,
                    comment="The version of the benchmark tool used.",
                ),
                insert_after="config",
            )
            batch_op.add_column(
                sa.Column(
                    "kernel_version",
                    sqlmodel.sql.sqltypes.AutoString(),
                    nullable=True,
                    comment="The kernel version of the server when the benchmark was run.",
                ),
                insert_after="framework_version",
            )
    else:
        op.add_column(
            benchmark_score_table_name,
            sa.Column(
                "framework_version",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
                comment="The version of the benchmark tool used.",
            ),
        )
        op.add_column(
            benchmark_score_table_name,
            sa.Column(
                "kernel_version",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
                comment="The kernel version of the server when the benchmark was run.",
            ),
        )


def downgrade() -> None:
    benchmark_score_table_name = scdize_suffix("benchmark_score")
    with op.batch_alter_table(benchmark_score_table_name, schema=None) as batch_op:
        batch_op.drop_column("kernel_version")
        batch_op.drop_column("framework_version")
