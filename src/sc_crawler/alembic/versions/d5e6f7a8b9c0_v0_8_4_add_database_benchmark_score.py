"""v0.8.4 add database_benchmark_score table

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-20 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
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


def upgrade() -> None:
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    is_scd = is_scd_migration()

    vendor_table = scdize_suffix("vendor")
    database_table = scdize_suffix("database")
    benchmark_table = scdize_suffix("benchmark")
    table_name = scdize_suffix("database_benchmark_score")

    primary_keys = (
        ("vendor_id", "database_id", "benchmark_id", "config", "observed_at")
        if is_scd
        else ("vendor_id", "database_id", "benchmark_id", "config")
    )
    foreign_keys = (
        (
            sa.ForeignKeyConstraint(
                ["benchmark_id"],
                [f"{benchmark_table}.benchmark_id"],
                name=op.f(f"fk_{table_name}_benchmark_id_{benchmark_table}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "database_id"],
                [f"{database_table}.vendor_id", f"{database_table}.database_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{database_table}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table}"),
            ),
        )
        if not is_scd
        else ()
    )

    op.create_table(
        table_name,
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
            comment="Reference to the Database.",
        ),
        sa.Column(
            "benchmark_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Benchmark.",
        ),
        sa.Column(
            "config",
            json_type,
            nullable=False,
            comment=(
                'Dictionary of config parameters of the specific benchmark, '
                'e.g. {"bandwidth": 4096}'
            ),
        ),
        sa.Column(
            "framework_version",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="The version of the benchmark tool used.",
        ),
        sa.Column(
            "kernel_version",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="The kernel version when the benchmark was run.",
        ),
        sa.Column(
            "score",
            sa.Float(),
            nullable=False,
            comment="The resulting score of the benchmark.",
        ),
        sa.Column(
            "score_breakdown",
            json_type,
            nullable=True,
            comment=(
                "Structured derivation of composite scores (e.g. workload profiles): "
                "per-component raw values, references, normalized values, weights, and "
                "coverage. Null for simple benchmark scores."
            ),
        ),
        sa.Column(
            "note",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional note, comment or context on the benchmark score.",
        ),
        sa.Column(
            "status",
            _enum("status", ("ACTIVE", "INACTIVE")),
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
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
        comment="Results of running Benchmark scenarios on managed Databases."
        if not is_scd
        else "SCD version of .tables.DatabaseBenchmarkScore.",
    )


def downgrade() -> None:
    op.drop_table(scdize_suffix("database_benchmark_score"))
