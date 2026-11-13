"""v0.11.0 add archived status and the archive_rule table

Schema changes only: records are set to ARCHIVED by the `pull` and `sync`
commands based on the archive rules, never by migrations.

Revision ID: 255dc3cde0c6
Revises: c7d8e9f0a1b2
Create Date: 2026-11-10 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "255dc3cde0c6"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_TABLES = (
    "benchmark",
    "benchmark_score",
    "compliance_framework",
    "country",
    "database",
    "database_price",
    "database_storage",
    "database_storage_price",
    "ipv4_price",
    "region",
    "server",
    "server_description",
    "server_price",
    "storage",
    "storage_price",
    "traffic_price",
    "vendor",
    "vendor_compliance_link",
    "zone",
)

_STATUSES = ("ACTIVE", "INACTIVE", "PLANNED_FOR_RETIREMENT", "RETIRED")


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def upgrade() -> None:
    is_postgresql = op.get_context().dialect.name == "postgresql"
    statuses = _STATUSES + ("ARCHIVED",)
    if is_postgresql:
        # SQLAlchemy stores Status member names (ACTIVE, …), not values.
        op.execute("ALTER TYPE status ADD VALUE IF NOT EXISTS 'ARCHIVED'")
        status_type = sa.dialects.postgresql.ENUM(
            *statuses, name="status", create_type=False
        )
        json_type = sa.dialects.postgresql.JSONB
    else:
        status_type = sa.Enum(*statuses, name="status")
        json_type = sa.JSON

    table_name = scdize_suffix("archive_rule")
    primary_key = ["table_name", "match", "successor"]
    if is_scd_migration():
        primary_key.append("observed_at")
    op.create_table(
        table_name,
        sa.Column(
            "table_name",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Name of the table of the archived record(s), e.g. `region`.",
        ),
        sa.Column(
            "match",
            json_type,
            nullable=False,
            comment='Primary key of the record to archive, or a subset of its columns to archive all records with those values, e.g. {"region_id": "2", "vendor_id": "hcloud"}.',
        ),
        sa.Column(
            "successor",
            json_type,
            nullable=False,
            comment="New values of the `match` columns identifying the successor of each archived record. Empty when there is no successor, or none that can be given as fixed values (see `reason`).",
        ),
        sa.Column(
            "reason",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Why the record(s) got archived.",
        ),
        sa.Column(
            "status",
            status_type,
            nullable=False,
            comment="Status of the resource (active or inactive).",
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(),
            nullable=False,
            comment="Timestamp of the last observation.",
        ),
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment=(
            "SCD version of .tables.ArchiveRule."
            if is_scd_migration()
            else "Rules archiving records that were replaced by another record or deliberately dropped."
        ),
    )


def downgrade() -> None:
    op.drop_table(scdize_suffix("archive_rule"))

    for table in _STATUS_TABLES:
        table_name = scdize_suffix(table)
        op.execute(
            f"""
            UPDATE {table_name}
            SET status = 'INACTIVE'
            WHERE status = 'ARCHIVED'
            """  # noqa: S608
        )

    if op.get_context().dialect.name != "postgresql":
        return

    # All status columns must be retyped when recreating the enum.
    op.execute("ALTER TYPE status RENAME TO status_old")
    op.execute(
        "CREATE TYPE status AS ENUM (" + ", ".join(f"'{v}'" for v in _STATUSES) + ")"
    )
    for table in _STATUS_TABLES:
        table_name = scdize_suffix(table)
        op.execute(
            f"""
            ALTER TABLE {table_name}
            ALTER COLUMN status TYPE status
            USING status::text::status
            """  # noqa: S608
        )
    op.execute("DROP TYPE status_old")
