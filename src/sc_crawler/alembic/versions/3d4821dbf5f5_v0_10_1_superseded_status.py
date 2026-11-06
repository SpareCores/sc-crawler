"""v0.10.1 add superseded status and mark former Hetzner datacenter regions as superseded

Revision ID: 3d4821dbf5f5
Revises: 37c49fd74cce
Create Date: 2026-10-19 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "3d4821dbf5f5"
down_revision: Union[str, None] = "37c49fd74cce"
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

_REGION_TABLES = (
    "region",
    "zone",
    "server_price",
    "storage_price",
    "traffic_price",
    "ipv4_price",
    "database_price",
    "database_storage_price",
)

# Former region_ids from the deprecated Hetzner /v1/datacenters endpoint,
# replaced by the location names (e.g. `fsn1`), see `_hcloud.py`.
_HCLOUD_LEGACY_REGION_IDS = ("2", "3", "4", "5", "6", "7")


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def _recreate_status_enum(values: tuple[str, ...]) -> None:
    """Recreate the status enum type and retype all status columns."""
    op.execute("ALTER TYPE status RENAME TO status_old")
    op.execute(
        "CREATE TYPE status AS ENUM (" + ", ".join(f"'{v}'" for v in values) + ")"
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


def upgrade() -> None:
    # SQLAlchemy stores Status member names (ACTIVE, …), not values.
    if is_scd_migration():
        # SCD tables are history (with huge price tables), so no table
        # rewrite and no data update: new versions are recorded via sync.
        if op.get_context().dialect.name == "postgresql":
            op.execute("ALTER TYPE status ADD VALUE IF NOT EXISTS 'SUPERSEDED'")
        return

    if op.get_context().dialect.name == "postgresql":
        # Not using ALTER TYPE ... ADD VALUE, as the new value could not be
        # used in the same transaction (see the UPDATE below).
        _recreate_status_enum(_STATUSES + ("SUPERSEDED",))

    region_ids = ", ".join(f"'{region_id}'" for region_id in _HCLOUD_LEGACY_REGION_IDS)
    for table in _REGION_TABLES:
        op.execute(
            f"""
            UPDATE {table}
            SET status = 'SUPERSEDED'
            WHERE vendor_id = 'hcloud'
              AND region_id IN ({region_ids})
            """  # noqa: S608
        )


def downgrade() -> None:
    for table in _STATUS_TABLES:
        table_name = scdize_suffix(table)
        op.execute(
            f"""
            UPDATE {table_name}
            SET status = 'INACTIVE'
            WHERE status = 'SUPERSEDED'
            """  # noqa: S608
        )

    if op.get_context().dialect.name == "postgresql":
        _recreate_status_enum(_STATUSES)
