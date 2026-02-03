"""v1.2.0-rename-datacenter-to-region-step2

Revision ID: dad8a1f0f455
Revises: 865f5ee9f624
Create Date: 2024-06-02 14:54:23.496459

"""

from typing import List, Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dad8a1f0f455"
down_revision: Union[str, None] = "865f5ee9f624"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def scdize_suffix(table_name: str) -> str:
    if op.get_context().config.attributes.get("scd"):
        return table_name + "_scd"
    return table_name


def scdize_pk_observed_at(pks: List) -> List:
    if op.get_context().config.attributes.get("scd"):
        return [*pks, "observed_at"]
    return pks


# need to provide the table schema for offline mode support
meta = sa.MetaData()

region_table = sa.Table(
    scdize_suffix("region"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "region_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Unique identifier, as called at the Vendor.",
    ),
    sa.Column(
        "name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly name.",
    ),
    sa.Column(
        "api_reference",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depening on the vendor and actual API endpoint.",
    ),
    sa.Column(
        "display_name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly reference (usually the id or name) of the resource.",
    ),
    sa.Column(
        "aliases",
        sa.JSON(),
        nullable=False,
        comment="List of other commonly used names for the same Datacenter.",
    ),
    sa.Column(
        "country_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Country, where the Datacenter is located.",
    ),
    sa.Column(
        "state",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional state/administrative area of the Datacenter's location within the Country.",
    ),
    sa.Column(
        "city",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional city name of the Datacenter's location.",
    ),
    sa.Column(
        "address_line",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional address line of the Datacenter's location.",
    ),
    sa.Column(
        "zip_code",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
        comment="Optional ZIP code of the Datacenter's location.",
    ),
    sa.Column(
        "lon",
        sa.Float(),
        nullable=True,
        comment="Longitude coordinate of the Datacenter's known or approximate location.",
    ),
    sa.Column(
        "lat",
        sa.Float(),
        nullable=True,
        comment="Latitude coordinate of the Datacenter's known or approximate location.",
    ),
    sa.Column(
        "founding_year",
        sa.Integer(),
        nullable=True,
        comment="4-digit year when the Datacenter was founded.",
    ),
    sa.Column(
        "green_energy",
        sa.Boolean(),
        nullable=True,
        comment="If the Datacenter is 100% powered by renewable energy.",
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
)


zone_table = sa.Table(
    scdize_suffix("zone"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "region_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Region.",
    ),
    sa.Column(
        "zone_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Unique identifier, as called at the Vendor.",
    ),
    sa.Column(
        "name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly name.",
    ),
    sa.Column(
        "api_reference",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depening on the vendor and actual API endpoint.",
    ),
    sa.Column(
        "display_name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Human-friendly reference (usually the id or name) of the resource.",
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
    extend_existing=True,
    comment="Availability zones of Regions.",
)


server_price_table = sa.Table(
    scdize_suffix("server_price"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "region_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Region.",
    ),
    sa.Column(
        "zone_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Zone.",
    ),
    sa.Column(
        "server_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Server.",
    ),
    sa.Column(
        "operating_system",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Operating System.",
    ),
    sa.Column(
        "allocation",
        sa.Enum("ONDEMAND", "RESERVED", "SPOT", name="allocation"),
        nullable=False,
        comment="Allocation method, e.g. on-demand or spot.",
    ),
    sa.Column(
        "unit",
        sa.Enum("YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"),
        nullable=False,
        comment="Billing unit of the pricing model.",
    ),
    sa.Column(
        "price",
        sa.Float(),
        nullable=False,
        comment="Actual price of a billing unit.",
    ),
    sa.Column(
        "price_upfront",
        sa.Float(),
        nullable=False,
        comment="Price to be paid when setting up the resource.",
    ),
    sa.Column(
        "price_tiered",
        sa.JSON(),
        nullable=False,
        comment="List of pricing tiers with min/max thresholds and actual prices.",
    ),
    sa.Column(
        "currency",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Currency of the prices.",
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
)

storage_price_table = sa.Table(
    scdize_suffix("storage_price"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "region_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Region.",
    ),
    sa.Column(
        "storage_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Storage.",
    ),
    sa.Column(
        "unit",
        sa.Enum("YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"),
        nullable=False,
        comment="Billing unit of the pricing model.",
    ),
    sa.Column(
        "price",
        sa.Float(),
        nullable=False,
        comment="Actual price of a billing unit.",
    ),
    sa.Column(
        "price_upfront",
        sa.Float(),
        nullable=False,
        comment="Price to be paid when setting up the resource.",
    ),
    sa.Column(
        "price_tiered",
        sa.JSON(),
        nullable=False,
        comment="List of pricing tiers with min/max thresholds and actual prices.",
    ),
    sa.Column(
        "currency",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Currency of the prices.",
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
)

traffic_price_table = sa.Table(
    scdize_suffix("traffic_price"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "region_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Region.",
    ),
    sa.Column(
        "direction",
        sa.Enum("IN", "OUT", name="trafficdirection"),
        nullable=False,
        comment="Direction of the traffic: inbound or outbound.",
    ),
    sa.Column(
        "unit",
        sa.Enum("YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"),
        nullable=False,
        comment="Billing unit of the pricing model.",
    ),
    sa.Column(
        "price",
        sa.Float(),
        nullable=False,
        comment="Actual price of a billing unit.",
    ),
    sa.Column(
        "price_upfront",
        sa.Float(),
        nullable=False,
        comment="Price to be paid when setting up the resource.",
    ),
    sa.Column(
        "price_tiered",
        sa.JSON(),
        nullable=False,
        comment="List of pricing tiers with min/max thresholds and actual prices.",
    ),
    sa.Column(
        "currency",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Currency of the prices.",
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
)

ipv4_price_table = sa.Table(
    scdize_suffix("ipv4_price"),
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Vendor.",
    ),
    sa.Column(
        "region_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Reference to the Region.",
    ),
    sa.Column(
        "unit",
        sa.Enum("YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH", name="priceunit"),
        nullable=False,
        comment="Billing unit of the pricing model.",
    ),
    sa.Column(
        "price",
        sa.Float(),
        nullable=False,
        comment="Actual price of a billing unit.",
    ),
    sa.Column(
        "price_upfront",
        sa.Float(),
        nullable=False,
        comment="Price to be paid when setting up the resource.",
    ),
    sa.Column(
        "price_tiered",
        sa.JSON(),
        nullable=False,
        comment="List of pricing tiers with min/max thresholds and actual prices.",
    ),
    sa.Column(
        "currency",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
        comment="Currency of the prices.",
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
)


def upgrade() -> None:
    """Adding back the constraints for the tables recreated in step1."""
    with op.batch_alter_table(
        scdize_suffix("region"),
        schema=None,
        copy_from=region_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_region")),
            scdize_pk_observed_at(["vendor_id", "region_id"]),
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('region')}_country_id_country")),
            "country",
            ["country_id"],
            ["country_id"],
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('region')}_vendor_id_vendor")),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )

    with op.batch_alter_table(scdize_suffix("zone"), copy_from=zone_table) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_zone")),
            scdize_pk_observed_at(["vendor_id", "region_id", "zone_id"]),
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('zone')}_vendor_id_vendor")),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('zone')}_vendor_id_region")),
            "region",
            ["vendor_id", "region_id"],
            ["vendor_id", "region_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("server_price"),
        schema=None,
        copy_from=server_price_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_server_price")),
            scdize_pk_observed_at(
                ["vendor_id", "region_id", "zone_id", "server_id", "allocation"]
            ),
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('server_price')}_vendor_id_vendor")),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('server_price')}_vendor_id_region")),
            "region",
            ["vendor_id", "region_id"],
            ["vendor_id", "region_id"],
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('server_price')}_vendor_id_zone")),
            "zone",
            ["vendor_id", "region_id", "zone_id"],
            ["vendor_id", "region_id", "zone_id"],
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('server_price')}_vendor_id_server")),
            "server",
            ["vendor_id", "server_id"],
            ["vendor_id", "server_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("storage_price"),
        schema=None,
        copy_from=storage_price_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_storage_price")),
            scdize_pk_observed_at(["vendor_id", "region_id", "storage_id"]),
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(f"fk_{scdize_suffix('storage_price')}_vendor_id_vendor")
            ),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(f"fk_{scdize_suffix('storage_price')}_vendor_id_region")
            ),
            "region",
            ["vendor_id", "region_id"],
            ["vendor_id", "region_id"],
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(f"fk_{scdize_suffix('storage_price')}_vendor_id_storage")
            ),
            "storage",
            ["vendor_id", "storage_id"],
            ["vendor_id", "storage_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("traffic_price"),
        schema=None,
        copy_from=traffic_price_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_traffic_price")),
            scdize_pk_observed_at(["vendor_id", "region_id", "direction"]),
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(f"fk_{scdize_suffix('traffic_price')}_vendor_id_vendor")
            ),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )
        batch_op.create_foreign_key(
            op.f(
                scdize_suffix(f"fk_{scdize_suffix('traffic_price')}_vendor_id_region")
            ),
            "region",
            ["vendor_id", "region_id"],
            ["vendor_id", "region_id"],
        )

    with op.batch_alter_table(
        scdize_suffix("ipv4_price"),
        schema=None,
        copy_from=ipv4_price_table,
        recreate="always",
    ) as batch_op:
        batch_op.create_primary_key(
            op.f(scdize_suffix("pk_ipv4_price")),
            scdize_pk_observed_at(["vendor_id", "region_id"]),
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('ipv4_price')}_vendor_id_vendor")),
            "vendor",
            ["vendor_id"],
            ["vendor_id"],
        )
        batch_op.create_foreign_key(
            op.f(scdize_suffix(f"fk_{scdize_suffix('ipv4_price')}_vendor_id_region")),
            "region",
            ["vendor_id", "region_id"],
            ["vendor_id", "region_id"],
        )


def downgrade() -> None:
    """Actually downgrading step 1."""
    with op.batch_alter_table(scdize_suffix("zone"), copy_from=zone_table) as batch_op:
        batch_op.alter_column(new_column_name="datacenter_id", column_name="region_id")
    with op.batch_alter_table(
        scdize_suffix("storage_price"), copy_from=storage_price_table
    ) as batch_op:
        batch_op.alter_column(new_column_name="datacenter_id", column_name="region_id")
    with op.batch_alter_table(
        scdize_suffix("server_price"), copy_from=server_price_table
    ) as batch_op:
        batch_op.alter_column(new_column_name="datacenter_id", column_name="region_id")
    with op.batch_alter_table(
        scdize_suffix("traffic_price"), copy_from=traffic_price_table
    ) as batch_op:
        batch_op.alter_column(new_column_name="datacenter_id", column_name="region_id")
    with op.batch_alter_table(
        scdize_suffix("ipv4_price"), copy_from=ipv4_price_table
    ) as batch_op:
        batch_op.alter_column(new_column_name="datacenter_id", column_name="region_id")

    with op.batch_alter_table(
        scdize_suffix("region"),
        schema=None,
        copy_from=region_table,
        recreate="always",
    ) as batch_op:
        batch_op.alter_column(new_column_name="datacenter_id", column_name="region_id")
    op.rename_table(scdize_suffix("region"), scdize_suffix("datacenter"))
