"""v0.3.3 migration reset

Revision ID: dad8a1f0f455
Revises:
Create Date: 2026-02-02 17:46:08.598626

"""

from typing import Sequence, Union

from alembic import op

from sc_crawler.alembic.table_helpers import (
    create_benchmark_score_table,
    create_benchmark_table,
    create_compliance_framework_table,
    create_country_table,
    create_ipv4_price_table,
    create_region_table,
    create_server_price_table,
    create_server_table,
    create_storage_price_table,
    create_storage_table,
    create_traffic_price_table,
    create_vendor_compliance_link_table,
    create_vendor_table,
    create_zone_table,
)

# revision identifiers, used by Alembic.
revision: str = "dad8a1f0f455"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def upgrade() -> None:
    is_scd = is_scd_migration()
    create_benchmark_table(is_scd)
    create_compliance_framework_table(is_scd)
    create_country_table(is_scd)
    create_vendor_table(is_scd)
    create_region_table(is_scd)
    create_server_table(is_scd)
    create_storage_table(is_scd)
    create_vendor_compliance_link_table(is_scd)
    create_zone_table(is_scd)
    create_benchmark_score_table(is_scd)
    create_ipv4_price_table(is_scd)
    create_server_price_table(is_scd)
    create_storage_price_table(is_scd)
    create_traffic_price_table(is_scd)


def downgrade() -> None:
    if is_scd_migration():
        op.drop_table("traffic_price_scd")
        op.drop_table("storage_price_scd")
        op.drop_table("server_price_scd")
        op.drop_table("ipv4_price_scd")
        op.drop_table("benchmark_score_scd")
        op.drop_table("zone_scd")
        op.drop_table("vendor_compliance_link_scd")
        op.drop_table("storage_scd")
        op.drop_table("server_scd")
        op.drop_table("region_scd")
        op.drop_table("vendor_scd")
        op.drop_table("country_scd")
        op.drop_table("compliance_framework_scd")
        op.drop_table("benchmark_scd")
    else:
        op.drop_table("traffic_price")
        op.drop_table("storage_price")
        op.drop_table("server_price")
        op.drop_table("ipv4_price")
        op.drop_table("benchmark_score")
        op.drop_table("zone")
        op.drop_table("vendor_compliance_link")
        op.drop_table("storage")
        op.drop_table("server")
        op.drop_table("region")
        op.drop_table("vendor")
        op.drop_table("country")
        op.drop_table("compliance_framework")
        op.drop_table("benchmark")

    if op.get_context().dialect.name == "postgresql":
        op.execute("DROP TYPE IF EXISTS status")
        op.execute("DROP TYPE IF EXISTS cpuallocation")
        op.execute("DROP TYPE IF EXISTS cpuarchitecture")
        op.execute("DROP TYPE IF EXISTS ddrgeneration")
        op.execute("DROP TYPE IF EXISTS storagetype")
        op.execute("DROP TYPE IF EXISTS priceunit")
        op.execute("DROP TYPE IF EXISTS allocation")
        op.execute("DROP TYPE IF EXISTS trafficdirection")
