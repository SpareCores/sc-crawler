"""v0.5.2 add vendor-specific billing fields

Revision ID: 055e00abdcb5
Revises: 8c5bd4869b90
Create Date: 2026-05-21 10:26:08.368521

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "055e00abdcb5"
down_revision: Union[str, None] = "8c5bd4869b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def get_vendor_table(is_scd: bool) -> sa.Table:
    is_postgresql = op.get_context().dialect.name == "postgresql"
    table_name = scdize_suffix("vendor")
    primary_keys = ("vendor_id", "observed_at") if is_scd else ("vendor_id",)
    foreign_keys = (
        (
            sa.ForeignKeyConstraint(
                ["country_id"],
                ["country.country_id"],
                name=op.f(f"fk_{table_name}_country_id_country"),
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
            comment="Unique identifier.",
        ),
        sa.Column(
            "name",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Human-friendly name.",
        ),
        sa.Column(
            "logo",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Publicly accessible URL to the image of the Vendor's logo.",
        ),
        sa.Column(
            "homepage",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Public homepage of the Vendor.",
        ),
        sa.Column(
            "country_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Country, where the Vendor's main headquarter is located.",
        ),
        sa.Column(
            "state",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional state/administrative area of the Vendor's location within the Country.",
        ),
        sa.Column(
            "city",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional city name of the Vendor's main location.",
        ),
        sa.Column(
            "address_line",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional address line of the Vendor's main location.",
        ),
        sa.Column(
            "zip_code",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional ZIP code of the Vendor's main location.",
        ),
        sa.Column(
            "founding_year",
            sa.Integer(),
            nullable=False,
            comment="4-digit year when the public cloud service of the Vendor was launched.",
        ),
        sa.Column(
            "status_page",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Public status page of the Vendor.",
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
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
        comment="SCD version of .tables.Vendor."
        if is_scd
        else "Compute resource vendors, such as cloud and server providers.",
    )


def upgrade() -> None:
    is_scd = is_scd_migration()
    vendor_table_name = scdize_suffix("vendor")
    vendor_table = get_vendor_table(is_scd)
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd
    if do_recreate_tables:
        with op.batch_alter_table(
            vendor_table_name,
            schema=None,
            copy_from=vendor_table,
            recreate="always",
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "stopped_server_charged",
                    sa.Boolean(),
                    nullable=True,
                    comment="If the Vendor charges for stopped servers.",
                ),
                insert_after="status_page",
            )
            batch_op.add_column(
                sa.Column(
                    "billing_increment_seconds",
                    sa.Integer(),
                    nullable=True,
                    comment="The smallest increment of time for which the Vendor bills for.",
                ),
                insert_after="stopped_server_charged",
            )
            batch_op.add_column(
                sa.Column(
                    "minimum_billing_seconds",
                    sa.Integer(),
                    nullable=True,
                    comment="The minimum amount of time for which the Vendor bills for.",
                ),
                insert_after="billing_increment_seconds",
            )
            batch_op.add_column(
                sa.Column(
                    "comment",
                    sqlmodel.sql.sqltypes.AutoString(),
                    nullable=True,
                    comment="Comment on the Vendor's billing.",
                ),
                insert_after="minimum_billing_seconds",
            )
    else:
        op.add_column(
            vendor_table_name,
            sa.Column(
                "stopped_server_charged",
                sa.Boolean(),
                nullable=True,
                comment="If the Vendor charges for stopped servers.",
            ),
        )
        op.add_column(
            vendor_table_name,
            sa.Column(
                "billing_increment_seconds",
                sa.Integer(),
                nullable=True,
                comment="The smallest increment of time for which the Vendor bills for.",
            ),
        )
        op.add_column(
            vendor_table_name,
            sa.Column(
                "minimum_billing_seconds",
                sa.Integer(),
                nullable=True,
                comment="The minimum amount of time for which the Vendor bills for.",
            ),
        )
        op.add_column(
            vendor_table_name,
            sa.Column(
                "comment",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
                comment="Comment on the Vendor's billing.",
            ),
        )


def downgrade() -> None:
    vendor_table_name = scdize_suffix("vendor")
    with op.batch_alter_table(vendor_table_name, schema=None) as batch_op:
        batch_op.drop_column("minimum_billing_seconds")
        batch_op.drop_column("billing_increment_seconds")
        batch_op.drop_column("stopped_server_charged")
        batch_op.drop_column("comment")
