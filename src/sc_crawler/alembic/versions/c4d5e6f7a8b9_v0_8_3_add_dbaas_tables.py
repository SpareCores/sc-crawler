"""v0.8.3 add dbaas tables

Revision ID: c4d5e6f7a8b9
Revises: 816a0ef08432
Create Date: 2026-07-14 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "816a0ef08432"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def _enum(name: str, values: tuple[str, ...], *, create_type: bool = False):
    is_postgresql = op.get_context().dialect.name == "postgresql"
    if is_postgresql:
        return sa.dialects.postgresql.ENUM(*values, name=name, create_type=create_type)
    return sa.Enum(*values, name=name)


def _drop_new_postgresql_enums() -> None:
    """Table drops do not remove PostgreSQL enum types."""
    if op.get_context().dialect.name != "postgresql":
        return
    bind = op.get_bind()
    for name, values in (
        ("databasestoragescope", ("DATA", "BACKUP")),
        ("databasesupportlevel", ("STANDARD",)),
        ("databaseengine", ("POSTGRESQL",)),
    ):
        sa.dialects.postgresql.ENUM(*values, name=name, create_type=False).drop(
            bind, checkfirst=True
        )


def _status_column():
    return sa.Column(
        "status",
        _enum("status", ("ACTIVE", "INACTIVE")),
        nullable=False,
        comment="Status of the resource (active or inactive).",
    )


def _observed_at_column():
    return sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
        comment="Timestamp of the last observation.",
    )


def _price_columns():
    return [
        sa.Column(
            "unit",
            _enum(
                "priceunit",
                ("YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH"),
            ),
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
    ]


def upgrade() -> None:
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    is_scd = is_scd_migration()
    vendor_table = scdize_suffix("vendor")
    region_table = scdize_suffix("region")

    database_table = scdize_suffix("database")
    database_pk = (
        ("vendor_id", "database_id", "observed_at")
        if is_scd
        else ("vendor_id", "database_id")
    )
    database_fks = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table}.vendor_id"],
                name=op.f(f"fk_{database_table}_vendor_id_{vendor_table}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        database_table,
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
            comment=(
                "How this resource is referenced in the vendor API calls. "
                "This is usually either the id or name of the resource, "
                "depending on the vendor and actual API endpoint."
            ),
        ),
        sa.Column(
            "display_name",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Human-friendly reference (usually the id or name) of the resource.",
        ),
        sa.Column(
            "description",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Short description.",
        ),
        sa.Column(
            "server_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional reference to a related Server SKU.",
        ),
        sa.Column(
            "engine",
            _enum("databaseengine", ("POSTGRESQL",), create_type=True),
            nullable=False,
            comment="Managed database engine.",
        ),
        sa.Column(
            "engine_versions",
            json_type,
            nullable=False,
            comment="Supported major engine versions merged onto the SKU row.",
        ),
        sa.Column(
            "family",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Database series or plan family slug.",
        ),
        sa.Column(
            "vcpus",
            sa.Integer(),
            nullable=True,
            comment="Number of virtual CPUs (vCPU) of the database SKU.",
        ),
        sa.Column(
            "memory_amount",
            sa.Integer(),
            nullable=True,
            comment="RAM amount (MiB) reported by the vendor.",
        ),
        sa.Column(
            "storage_size",
            sa.Integer(),
            nullable=True,
            comment="Bundled storage size (GB), when included in the SKU.",
        ),
        sa.Column(
            "ha_supported",
            sa.Boolean(),
            nullable=True,
            comment="If high availability is supported for the SKU.",
        ),
        sa.Column(
            "storage_autoscaling",
            sa.Boolean(),
            nullable=True,
            comment="If storage can be expanded beyond the bundled minimum.",
        ),
        sa.Column(
            "scheduled_backups",
            sa.Boolean(),
            nullable=True,
            comment="If scheduled/automated snapshot backups are supported.",
        ),
        sa.Column(
            "continuous_backups",
            sa.Integer(),
            nullable=True,
            comment="Point-in-time recovery retention in days.",
        ),
        sa.Column(
            "engine_auto_upgrade",
            sa.Boolean(),
            nullable=True,
            comment="If automatic engine version upgrades are supported.",
        ),
        sa.Column(
            "autotuning",
            sa.Boolean(),
            nullable=True,
            comment="If vendor autotuning is available.",
        ),
        sa.Column(
            "custom_config",
            sa.Boolean(),
            nullable=True,
            comment="If custom configuration parameters are supported.",
        ),
        sa.Column(
            "custom_extensions",
            sa.Boolean(),
            nullable=True,
            comment="If custom extensions are supported.",
        ),
        sa.Column(
            "support_level",
            _enum("databasesupportlevel", ("STANDARD",), create_type=True),
            nullable=True,
            comment="Vendor support tier for the SKU.",
        ),
        sa.Column(
            "sla",
            sa.Float(),
            nullable=True,
            comment="Service level agreement as a percentage, e.g. 99.95.",
        ),
        _status_column(),
        _observed_at_column(),
        *database_fks,
        sa.PrimaryKeyConstraint(*database_pk, name=op.f(f"pk_{database_table}")),
        comment="Managed database SKUs."
        if not is_scd
        else "SCD version of .tables.Database.",
    )

    database_price_table = scdize_suffix("database_price")
    database_price_pk = (
        ("vendor_id", "region_id", "database_id", "allocation", "observed_at")
        if is_scd
        else ("vendor_id", "region_id", "database_id", "allocation")
    )
    database_price_fks = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table}.vendor_id"],
                name=op.f(f"fk_{database_price_table}_vendor_id_{vendor_table}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "region_id"],
                [f"{region_table}.vendor_id", f"{region_table}.region_id"],
                name=op.f(f"fk_{database_price_table}_vendor_id_{region_table}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "database_id"],
                [f"{database_table}.vendor_id", f"{database_table}.database_id"],
                name=op.f(f"fk_{database_price_table}_vendor_id_{database_table}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        database_price_table,
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
            "database_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Database.",
        ),
        sa.Column(
            "allocation",
            _enum("allocation", ("ONDEMAND", "RESERVED", "SPOT")),
            nullable=False,
            comment="Allocation method, e.g. on-demand or spot.",
        ),
        *_price_columns(),
        _status_column(),
        _observed_at_column(),
        *database_price_fks,
        sa.PrimaryKeyConstraint(
            *database_price_pk, name=op.f(f"pk_{database_price_table}")
        ),
        comment="Managed database SKU prices per Region."
        if not is_scd
        else "SCD version of .tables.DatabasePrice.",
    )

    database_storage_table = scdize_suffix("database_storage")
    database_storage_pk = (
        ("vendor_id", "database_storage_id", "observed_at")
        if is_scd
        else ("vendor_id", "database_storage_id")
    )
    database_storage_fks = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table}.vendor_id"],
                name=op.f(f"fk_{database_storage_table}_vendor_id_{vendor_table}"),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        database_storage_table,
        sa.Column(
            "vendor_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Vendor.",
        ),
        sa.Column(
            "database_storage_id",
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
            "description",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Short description.",
        ),
        sa.Column(
            "scope",
            _enum("databasestoragescope", ("DATA", "BACKUP"), create_type=True),
            nullable=False,
            comment="Scope of the storage product, e.g. data or backup.",
        ),
        sa.Column(
            "redundancy",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Redundancy model, e.g. LRS or GRS.",
        ),
        sa.Column(
            "min_size",
            sa.Integer(),
            nullable=True,
            comment="Minimum required size (GB).",
        ),
        sa.Column(
            "max_size",
            sa.Integer(),
            nullable=True,
            comment="Maximum possible size (GB).",
        ),
        sa.Column(
            "max_iops",
            sa.Integer(),
            nullable=True,
            comment="Maximum Input/Output Operations Per Second.",
        ),
        sa.Column(
            "max_throughput",
            sa.Integer(),
            nullable=True,
            comment="Maximum Throughput (MB/s).",
        ),
        _status_column(),
        _observed_at_column(),
        *database_storage_fks,
        sa.PrimaryKeyConstraint(
            *database_storage_pk, name=op.f(f"pk_{database_storage_table}")
        ),
        comment="Managed database storage products."
        if not is_scd
        else "SCD version of .tables.DatabaseStorage.",
    )

    database_storage_price_table = scdize_suffix("database_storage_price")
    database_storage_price_pk = (
        ("vendor_id", "region_id", "database_storage_id", "observed_at")
        if is_scd
        else ("vendor_id", "region_id", "database_storage_id")
    )
    database_storage_price_fks = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table}.vendor_id"],
                name=op.f(
                    f"fk_{database_storage_price_table}_vendor_id_{vendor_table}"
                ),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "region_id"],
                [f"{region_table}.vendor_id", f"{region_table}.region_id"],
                name=op.f(
                    f"fk_{database_storage_price_table}_vendor_id_{region_table}"
                ),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "database_storage_id"],
                [
                    f"{database_storage_table}.vendor_id",
                    f"{database_storage_table}.database_storage_id",
                ],
                name=op.f(
                    f"fk_{database_storage_price_table}_vendor_id_{database_storage_table}"
                ),
            ),
        )
        if not is_scd
        else ()
    )
    op.create_table(
        database_storage_price_table,
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
            "database_storage_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the DatabaseStorage.",
        ),
        *_price_columns(),
        _status_column(),
        _observed_at_column(),
        *database_storage_price_fks,
        sa.PrimaryKeyConstraint(
            *database_storage_price_pk,
            name=op.f(f"pk_{database_storage_price_table}"),
        ),
        comment="Managed database storage prices in each Region."
        if not is_scd
        else "SCD version of .tables.DatabaseStoragePrice.",
    )


def downgrade() -> None:
    for table in (
        "database_storage_price",
        "database_storage",
        "database_price",
        "database",
    ):
        op.drop_table(scdize_suffix(table))
    _drop_new_postgresql_enums()
