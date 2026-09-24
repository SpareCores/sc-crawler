"""v0.9.3 cast observed_at to TIMESTAMP WITH TIME ZONE (PostgreSQL)

Revision ID: c7e8f9a0b1c2
Revises: b1c2d3e4f5a6
Create Date: 2026-09-22 13:42:54.000000

Aligns PostgreSQL `observed_at` columns with SQLModel 0.0.45+ UTCDateTime
(DateTime(timezone=True)). Existing naive values are interpreted as UTC.

No-op on SQLite (column data type unchanged there).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c7e8f9a0b1c2"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables with MetaColumns.observed_at (standard and SCD via scdize_suffix).
_OBSERVED_AT_TABLES = (
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


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table in _OBSERVED_AT_TABLES:
        table_name = scdize_suffix(table)
        op.execute(
            f"""
            ALTER TABLE {table_name}
            ALTER COLUMN observed_at TYPE TIMESTAMP WITH TIME ZONE
            USING observed_at AT TIME ZONE 'UTC'
            """  # noqa: S608
        )


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    for table in _OBSERVED_AT_TABLES:
        table_name = scdize_suffix(table)
        op.execute(
            f"""
            ALTER TABLE {table_name}
            ALTER COLUMN observed_at TYPE TIMESTAMP WITHOUT TIME ZONE
            USING observed_at AT TIME ZONE 'UTC'
            """  # noqa: S608
        )
