"""v1.1.4-benchmarks

Revision ID: c8d2054e68eb
Revises: f6bf6152039a
Create Date: 2024-05-29 21:08:39.835479

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d2054e68eb"
down_revision: Union[str, None] = "f6bf6152039a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_context().config.attributes.get("scd"):
        op.create_table(
            "benchmark_scd",
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
                sa.JSON(),
                nullable=False,
                comment='A dictionary of descriptions on the framework-specific config options, e.g. {"bandwidth": "Memory amount to use for compression in MB."}.',
            ),
            sa.Column(
                "measurement",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
                comment="The name of measurement recoreded in the benchmark.",
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
            sa.PrimaryKeyConstraint("benchmark_id", "observed_at"),
            comment="SCD version of .tables.Benchmark.",
        )
        op.create_table(
            "benchmark_score_scd",
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
                sa.JSON(),
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
            sa.ForeignKeyConstraint(
                ["benchmark_id"],
                ["benchmark.benchmark_id"],
            ),
            sa.ForeignKeyConstraint(
                ["server_id"],
                ["server.server_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "server_id"],
                ["benchmark_score.vendor_id", "benchmark_score.server_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint(
                "vendor_id", "server_id", "benchmark_id", "config", "observed_at"
            ),
            comment="SCD version of .tables.BenchmarkScores.",
        )
    else:
        op.create_table(
            "benchmark",
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
                sa.JSON(),
                nullable=False,
                comment='A dictionary of descriptions on the framework-specific config options, e.g. {"bandwidth": "Memory amount to use for compression in MB."}.',
            ),
            sa.Column(
                "measurement",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
                comment="The name of measurement recoreded in the benchmark.",
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
            sa.PrimaryKeyConstraint("benchmark_id"),
            comment="Benchmark scenario definitions.",
        )
        op.create_table(
            "benchmark_score",
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
                sa.JSON(),
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
            sa.ForeignKeyConstraint(
                ["benchmark_id"],
                ["benchmark.benchmark_id"],
            ),
            sa.ForeignKeyConstraint(
                ["server_id"],
                ["server.server_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "server_id"],
                ["benchmark_score.vendor_id", "benchmark_score.server_id"],
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
            ),
            sa.PrimaryKeyConstraint("vendor_id", "server_id", "benchmark_id", "config"),
            comment="Results of running Benchmark scenarios on Servers.",
        )


def downgrade() -> None:
    if op.get_context().config.attributes.get("scd"):
        op.drop_table("benchmark_score_scd")
        op.drop_table("benchmark_scd")
    else:
        op.drop_table("benchmark_score")
        op.drop_table("benchmark")
