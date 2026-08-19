"""v0.9.0 merge database_benchmark_score into benchmark_score

Revision ID: a9b0c1d2e3f4
Revises: f97756a9e15f
Create Date: 2026-08-10 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, None] = "f97756a9e15f"
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


def get_benchmark_score_table(is_scd: bool) -> sa.Table:
    """Pre-v0.9.0 ``benchmark_score`` schema (copy_from source)."""
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    table_name = scdize_suffix("benchmark_score")
    vendor_table = scdize_suffix("vendor")
    server_table = scdize_suffix("server")
    benchmark_table = scdize_suffix("benchmark")
    primary_keys = (
        ("vendor_id", "server_id", "benchmark_id", "config", "observed_at")
        if is_scd
        else ("vendor_id", "server_id", "benchmark_id", "config")
    )
    foreign_keys = (
        (
            sa.ForeignKeyConstraint(
                ["benchmark_id"],
                [f"{benchmark_table}.benchmark_id"],
                name=op.f(f"fk_{table_name}_benchmark_id_{benchmark_table}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "server_id"],
                [f"{server_table}.vendor_id", f"{server_table}.server_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{server_table}"),
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
            comment=(
                "Dictionary of config parameters of the specific benchmark, "
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
            comment="The kernel version of the server when the benchmark was run.",
        ),
        sa.Column(
            "score",
            sa.Float(),
            nullable=False,
            comment="The resulting score of the benchmark.",
        ),
        sa.Column(
            "score_breakdown",
            json_type(),
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
        comment=(
            "SCD version of .tables.BenchmarkScore."
            if is_scd
            else "Results of running Benchmark scenarios on Servers."
        ),
    )


def get_benchmark_score_table_mid(is_scd: bool) -> sa.Table:
    """Mid-upgrade schema: resource_* + environment, still has kernel_version."""
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    table_name = scdize_suffix("benchmark_score")
    vendor_table = scdize_suffix("vendor")
    benchmark_table = scdize_suffix("benchmark")
    primary_keys = (
        (
            "vendor_id",
            "benchmark_id",
            "resource_type",
            "resource_id",
            "config",
            "observed_at",
        )
        if is_scd
        else (
            "vendor_id",
            "benchmark_id",
            "resource_type",
            "resource_id",
            "config",
        )
    )
    foreign_keys = (
        (
            sa.ForeignKeyConstraint(
                ["benchmark_id"],
                [f"{benchmark_table}.benchmark_id"],
                name=op.f(f"fk_{table_name}_benchmark_id_{benchmark_table}"),
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
            "benchmark_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Benchmark.",
        ),
        sa.Column(
            "resource_type",
            _enum("resourcetype", ("SERVER", "DATABASE")),
            nullable=False,
            comment="Kind of resource the score refers to.",
        ),
        sa.Column(
            "resource_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the resource (see resource_type).",
        ),
        sa.Column(
            "config",
            json_type(),
            nullable=False,
            comment=(
                "Dictionary of config parameters of the specific benchmark, "
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
            comment="The kernel version of the server when the benchmark was run.",
        ),
        sa.Column(
            "environment",
            json_type(),
            nullable=True,
            comment=(
                "Extensible environment details "
                "(e.g. kernel_version, database_engine_version)."
            ),
        ),
        sa.Column(
            "score",
            sa.Float(),
            nullable=False,
            comment="The resulting score of the benchmark.",
        ),
        sa.Column(
            "score_breakdown",
            json_type(),
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
        comment=(
            "SCD version of .tables.BenchmarkScore."
            if is_scd
            else "Results of running Benchmark scenarios on Servers or managed Databases."
        ),
    )


def upgrade() -> None:
    is_scd = is_scd_migration()
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    table_name = scdize_suffix("benchmark_score")
    table = get_benchmark_score_table(is_scd)
    db_score_name = scdize_suffix("database_benchmark_score")
    server_table = scdize_suffix("server")
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd

    resource_type_comment = "Kind of resource the score refers to."
    resource_id_comment = "Reference to the resource (see resource_type)."
    environment_comment = (
        "Extensible environment details (e.g. kernel_version, database_engine_version)."
    )

    # Existing rows are server scores.
    _upgrade_column_order = (
        "vendor_id",
        "benchmark_id",
        "resource_type",
        "server_id",  # → resource_id
        "config",
        "framework_version",
        "kernel_version",
        "environment",
        "score",
        "score_breakdown",
        "note",
        "status",
        "observed_at",
    )
    primary_keys = (
        (
            "vendor_id",
            "benchmark_id",
            "resource_type",
            "resource_id",
            "config",
            "observed_at",
        )
        if is_scd
        else (
            "vendor_id",
            "benchmark_id",
            "resource_type",
            "resource_id",
            "config",
        )
    )
    # batch_alter keeps the pre-rename column key after rename; PK cols must use that key.
    batch_primary_keys = (
        (
            "vendor_id",
            "benchmark_id",
            "resource_type",
            "server_id",
            "config",
            "observed_at",
        )
        if is_scd
        else (
            "vendor_id",
            "benchmark_id",
            "resource_type",
            "server_id",
            "config",
        )
    )

    if do_recreate_tables:
        with op.batch_alter_table(
            table_name,
            schema=None,
            copy_from=table,
            recreate="always",
            partial_reordering=[_upgrade_column_order],
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "resource_type",
                    sa.Enum("SERVER", "DATABASE", name="resourcetype"),
                    nullable=False,
                    server_default="SERVER",
                    comment=resource_type_comment,
                ),
            )
            batch_op.alter_column(
                "server_id",
                new_column_name="resource_id",
                comment=resource_id_comment,
            )
            batch_op.add_column(
                sa.Column(
                    "environment",
                    json_type(),
                    nullable=True,
                    comment=environment_comment,
                ),
            )
            if not is_scd:
                batch_op.drop_constraint(
                    op.f(f"fk_{table_name}_vendor_id_{server_table}"),
                    type_="foreignkey",
                )
            batch_op.drop_constraint(op.f(f"pk_{table_name}"), type_="primary")
            batch_op.create_primary_key(
                op.f(f"pk_{table_name}"), list(batch_primary_keys)
            )
    else:
        # batch_alter creates new enums; create explicitly only when not recreating.
        if is_postgresql:
            sa.Enum("SERVER", "DATABASE", name="resourcetype").create(
                op.get_bind(), checkfirst=True
            )
        op.add_column(
            table_name,
            sa.Column(
                "resource_type",
                _enum("resourcetype", ("SERVER", "DATABASE")),
                nullable=False,
                server_default="SERVER",
                comment=resource_type_comment,
            ),
        )
        op.alter_column(
            table_name,
            "server_id",
            new_column_name="resource_id",
            comment=resource_id_comment,
        )
        op.add_column(
            table_name,
            sa.Column(
                "environment",
                json_type(),
                nullable=True,
                comment=environment_comment,
            ),
        )
        op.drop_constraint(
            op.f(f"fk_{table_name}_vendor_id_{server_table}"),
            table_name,
            type_="foreignkey",
        )
        op.drop_constraint(op.f(f"pk_{table_name}"), table_name, type_="primary")
        op.create_primary_key(
            op.f(f"pk_{table_name}"),
            table_name,
            list(primary_keys),
        )

    if is_postgresql:
        op.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET environment = jsonb_build_object('kernel_version', kernel_version)
                WHERE kernel_version IS NOT NULL
                """  # noqa: S608
            )
        )
    else:
        op.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET environment = json_object('kernel_version', kernel_version)
                WHERE kernel_version IS NOT NULL
                """  # noqa: S608
            )
        )

    if do_recreate_tables and not is_postgresql:
        with op.batch_alter_table(
            table_name,
            schema=None,
            copy_from=get_benchmark_score_table_mid(is_scd),
            recreate="always",
        ) as batch_op:
            batch_op.drop_column("kernel_version")
            batch_op.alter_column("resource_type", server_default=None)
    else:
        op.drop_column(table_name, "kernel_version")
        if is_postgresql:
            op.alter_column(
                table_name,
                "resource_type",
                server_default=None,
                existing_nullable=False,
            )

    if is_postgresql:
        op.execute(
            sa.text(
                f"COMMENT ON TABLE {table_name} IS "
                "'Results of running Benchmark scenarios on Servers or managed Databases.'"
            )
        )

    op.drop_table(db_score_name)


def downgrade() -> None:
    is_scd = is_scd_migration()
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    table_name = scdize_suffix("benchmark_score")
    db_score_name = scdize_suffix("database_benchmark_score")
    vendor_table = scdize_suffix("vendor")
    server_table = scdize_suffix("server")
    database_table = scdize_suffix("database")
    benchmark_table = scdize_suffix("benchmark")
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd

    op.create_table(
        db_score_name,
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
            json_type(),
            nullable=False,
            comment=(
                "Dictionary of config parameters of the specific benchmark, "
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
            "score",
            sa.Float(),
            nullable=False,
            comment="The resulting score of the benchmark.",
        ),
        sa.Column(
            "score_breakdown",
            json_type(),
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
        *(
            ()
            if is_scd
            else (
                sa.ForeignKeyConstraint(
                    ["benchmark_id"],
                    [f"{benchmark_table}.benchmark_id"],
                    name=op.f(f"fk_{db_score_name}_benchmark_id_{benchmark_table}"),
                ),
                sa.ForeignKeyConstraint(
                    ["vendor_id", "database_id"],
                    [f"{database_table}.vendor_id", f"{database_table}.database_id"],
                    name=op.f(f"fk_{db_score_name}_vendor_id_{database_table}"),
                ),
                sa.ForeignKeyConstraint(
                    ["vendor_id"],
                    [f"{vendor_table}.vendor_id"],
                    name=op.f(f"fk_{db_score_name}_vendor_id_{vendor_table}"),
                ),
            )
        ),
        sa.PrimaryKeyConstraint(
            *(
                ("vendor_id", "database_id", "benchmark_id", "config", "observed_at")
                if is_scd
                else ("vendor_id", "database_id", "benchmark_id", "config")
            ),
            name=op.f(f"pk_{db_score_name}"),
        ),
        comment=(
            "SCD version of .tables.DatabaseBenchmarkScore."
            if is_scd
            else "Results of running Benchmark scenarios on managed Databases."
        ),
    )

    op.execute(
        sa.text(
            f"""
            INSERT INTO {db_score_name} (
                vendor_id, database_id, benchmark_id, config,
                framework_version, score, score_breakdown, note, status, observed_at
            )
            SELECT
                vendor_id, resource_id, benchmark_id, config,
                framework_version, score, score_breakdown, note, status, observed_at
            FROM {table_name}
            WHERE resource_type = 'DATABASE'
            """  # noqa: S608
        )
    )
    op.execute(
        sa.text(
            f"""
            DELETE FROM {table_name}
            WHERE resource_type = 'DATABASE'
            """  # noqa: S608
        )
    )

    op.add_column(
        table_name,
        sa.Column(
            "kernel_version",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="The kernel version of the server when the benchmark was run.",
        ),
    )
    if is_postgresql:
        op.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET kernel_version = environment ->> 'kernel_version'
                WHERE environment IS NOT NULL
                """  # noqa: S608
            )
        )
    else:
        op.execute(
            sa.text(
                f"""
                UPDATE {table_name}
                SET kernel_version = json_extract(environment, '$.kernel_version')
                WHERE environment IS NOT NULL
                """  # noqa: S608
            )
        )

    _downgrade_column_order = (
        "vendor_id",
        "resource_id",  # → server_id
        "benchmark_id",
        "config",
        "framework_version",
        "kernel_version",
        "score",
        "score_breakdown",
        "note",
        "status",
        "observed_at",
    )
    primary_keys = (
        ("vendor_id", "server_id", "benchmark_id", "config", "observed_at")
        if is_scd
        else ("vendor_id", "server_id", "benchmark_id", "config")
    )
    # batch_alter keeps the pre-rename column key after rename; PK/FK cols must use that key.
    batch_primary_keys = (
        ("vendor_id", "resource_id", "benchmark_id", "config", "observed_at")
        if is_scd
        else ("vendor_id", "resource_id", "benchmark_id", "config")
    )
    table_mid = get_benchmark_score_table_mid(is_scd)

    if do_recreate_tables:
        with op.batch_alter_table(
            table_name,
            schema=None,
            copy_from=table_mid,
            recreate="always",
            partial_reordering=[_downgrade_column_order],
        ) as batch_op:
            batch_op.drop_column("environment")
            batch_op.drop_column("resource_type")
            batch_op.alter_column(
                "resource_id",
                new_column_name="server_id",
                comment="Reference to the Server.",
            )
            batch_op.drop_constraint(op.f(f"pk_{table_name}"), type_="primary")
            batch_op.create_primary_key(
                op.f(f"pk_{table_name}"), list(batch_primary_keys)
            )
            if not is_scd:
                batch_op.create_foreign_key(
                    op.f(f"fk_{table_name}_vendor_id_{server_table}"),
                    server_table,
                    ["vendor_id", "resource_id"],
                    ["vendor_id", "server_id"],
                )
    else:
        # Drop PK before removing/renaming PK columns (PG CASCADE on drop_column
        # would remove pk_benchmark_score and a later drop_constraint would fail).
        op.drop_constraint(op.f(f"pk_{table_name}"), table_name, type_="primary")
        op.drop_column(table_name, "environment")
        op.drop_column(table_name, "resource_type")
        op.alter_column(
            table_name,
            "resource_id",
            new_column_name="server_id",
            comment="Reference to the Server.",
        )
        op.create_primary_key(
            op.f(f"pk_{table_name}"),
            table_name,
            list(primary_keys),
        )
        op.create_foreign_key(
            op.f(f"fk_{table_name}_vendor_id_{server_table}"),
            table_name,
            server_table,
            ["vendor_id", "server_id"],
            ["vendor_id", "server_id"],
        )

    if is_postgresql:
        op.execute(
            sa.text(
                f"COMMENT ON TABLE {table_name} IS "
                "'Results of running Benchmark scenarios on Servers.'"
            )
        )
        sa.Enum(name="resourcetype").drop(op.get_bind(), checkfirst=True)
