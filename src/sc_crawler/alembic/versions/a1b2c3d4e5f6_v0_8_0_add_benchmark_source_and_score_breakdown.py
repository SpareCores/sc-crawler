"""v0.8.0 add benchmark source and score breakdown

Revision ID: a1b2c3d4e5f6
Revises: fee26389b819
Create Date: 2026-06-28 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "fee26389b819"
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
            "category",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Category of the resource.",
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
            "framework_version",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="The version of the benchmark tool used.",
        ),
        sa.Column(
            "kernel_version",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="The kernel version of the server when the benchmark was run.",
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
        *foreign_keys,
        sa.PrimaryKeyConstraint(
            *primary_keys,
            name=op.f(f"pk_{table_name}"),
        ),
        comment="SCD version of .tables.BenchmarkScore."
        if is_scd
        else "Results of running Benchmark scenarios on Servers.",
    )


def upgrade() -> None:
    is_scd = is_scd_migration()
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    benchmark_table_name = scdize_suffix("benchmark")
    benchmark_table = get_benchmark_table(is_scd)
    benchmark_score_table_name = scdize_suffix("benchmark_score")
    benchmark_score_table = get_benchmark_score_table(is_scd)
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd

    source_comment = (
        "How the benchmark score is produced. A discriminated object keyed by "
        "'kind': 'measured' (directly observed), 'extrapolated' (derived from this "
        "server's own measurements; carries 'derived_from' + 'note'), or 'compound' "
        "(aggregated across component benchmarks; carries 'aggregation', "
        "'normalization', and the 'components' recipe)."
    )
    benchmark_note_comment = (
        "Optional caveat/comment on how to interpret the metric, surfaced as a "
        "warning/info badge (e.g. limited scaling on high vCPU counts, or "
        "independence from vCPU count). Null when there is nothing to flag."
    )
    score_breakdown_comment = (
        "Structured derivation of composite scores (e.g. workload profiles): "
        "per-component raw values, references, normalized values, weights, and "
        "coverage. Null for simple benchmark scores."
    )

    if do_recreate_tables:
        with op.batch_alter_table(
            benchmark_table_name,
            schema=None,
            copy_from=benchmark_table,
            recreate="always",
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "source",
                    json_type(),
                    nullable=True,
                    comment=source_comment,
                ),
                insert_after="category",
            )
            batch_op.add_column(
                sa.Column(
                    "note",
                    sqlmodel.sql.sqltypes.AutoString(),
                    nullable=True,
                    comment=benchmark_note_comment,
                ),
                insert_after="description",
            )
        with op.batch_alter_table(
            benchmark_score_table_name,
            schema=None,
            copy_from=benchmark_score_table,
            recreate="always",
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "score_breakdown",
                    json_type(),
                    nullable=True,
                    comment=score_breakdown_comment,
                ),
                insert_after="score",
            )
    else:
        op.add_column(
            benchmark_table_name,
            sa.Column(
                "source",
                json_type(),
                nullable=True,
                comment=source_comment,
            ),
        )
        op.add_column(
            benchmark_table_name,
            sa.Column(
                "note",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
                comment=benchmark_note_comment,
            ),
        )
        op.add_column(
            benchmark_score_table_name,
            sa.Column(
                "score_breakdown",
                json_type(),
                nullable=True,
                comment=score_breakdown_comment,
            ),
        )


def downgrade() -> None:
    is_scd = is_scd_migration()
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    benchmark_table_name = scdize_suffix("benchmark")
    benchmark_table = get_benchmark_table(is_scd)
    benchmark_score_table_name = scdize_suffix("benchmark_score")
    benchmark_score_table = get_benchmark_score_table(is_scd)

    _insert_column_after(
        benchmark_table,
        sa.Column("source", json_type(), nullable=True),
        "category",
    )
    _insert_column_after(
        benchmark_table,
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        "description",
    )
    _insert_column_after(
        benchmark_score_table,
        sa.Column("score_breakdown", json_type(), nullable=True),
        "score",
    )

    with op.batch_alter_table(
        benchmark_table_name, schema=None, copy_from=benchmark_table
    ) as batch_op:
        batch_op.drop_column("note")
        batch_op.drop_column("source")
    with op.batch_alter_table(
        benchmark_score_table_name,
        schema=None,
        copy_from=benchmark_score_table,
    ) as batch_op:
        batch_op.drop_column("score_breakdown")
