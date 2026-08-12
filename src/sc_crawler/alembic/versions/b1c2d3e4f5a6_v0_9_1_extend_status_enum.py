"""v0.9.1 extend status enum for server/database retirement

Revision ID: b1c2d3e4f5a6
Revises: a9b0c1d2e3f4
Create Date: 2026-08-12 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a9b0c1d2e3f4"
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


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def upgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return
    # SQLAlchemy stores Status member names (ACTIVE, …), not values.
    op.execute("ALTER TYPE status ADD VALUE IF NOT EXISTS 'PLANNED_FOR_RETIREMENT'")
    op.execute("ALTER TYPE status ADD VALUE IF NOT EXISTS 'RETIRED'")


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return

    for table in ("server", "database"):
        table_name = scdize_suffix(table)
        op.execute(
            f"""
            UPDATE {table_name}
            SET status = 'ACTIVE'
            WHERE status = 'PLANNED_FOR_RETIREMENT'
            """  # noqa: S608
        )
        op.execute(
            f"""
            UPDATE {table_name}
            SET status = 'INACTIVE'
            WHERE status = 'RETIRED'
            """  # noqa: S608
        )

    # All status columns must be retyped when recreating the enum.
    op.execute("ALTER TYPE status RENAME TO status_old")
    op.execute("CREATE TYPE status AS ENUM ('ACTIVE', 'INACTIVE')")
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
