"""v0.5.1 add benchmark category

Revision ID: 8c5bd4869b90
Revises: c1287bd79bb4
Create Date: 2026-04-20 17:54:33.402234

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c5bd4869b90"
down_revision: Union[str, None] = "c1287bd79bb4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def get_benchmark_table(is_scd: bool) -> sa.Table:
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
            json_type,
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
            sa.dialects.postgresql.ENUM(
                "ACTIVE",
                "INACTIVE",
                name="status",
                create_type=False,
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
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Benchmark."
        if is_scd
        else "Benchmark scenario definitions.",
    )


def upgrade() -> None:
    is_scd = is_scd_migration()
    benchmark_table_name = scdize_suffix("benchmark")
    benchmark_table = get_benchmark_table(is_scd)
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd
    if do_recreate_tables:
        with op.batch_alter_table(
            benchmark_table_name,
            schema=None,
            copy_from=benchmark_table,
            recreate="always",
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "category",
                    sqlmodel.sql.sqltypes.AutoString(),
                    nullable=True,
                    comment="Category of the resource.",
                ),
                insert_after="name",
            )
    else:
        op.add_column(
            benchmark_table_name,
            sa.Column(
                "category",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
                comment="Category of the resource.",
            ),
        )


def downgrade() -> None:
    benchmark_score_table_name = scdize_suffix("benchmark")
    with op.batch_alter_table(benchmark_score_table_name, schema=None) as batch_op:
        batch_op.drop_column("category")
