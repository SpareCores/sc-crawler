"""v0.7.0 add server description table

Revision ID: fee26389b819
Revises: f0273cb124f6
Create Date: 2026-06-19 15:40:12.283899

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fee26389b819"
down_revision: Union[str, None] = "f0273cb124f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def upgrade() -> None:
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    table_name = scdize_suffix("server_description")
    primary_key = (
        ("vendor_id", "server_id", "observed_at")
        if is_scd_migration()
        else ("vendor_id", "server_id")
    )
    foreign_keys = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id", "server_id"],
                ["server.vendor_id", "server.server_id"],
                name=op.f("fk_server_description_vendor_id_server"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                ["vendor.vendor_id"],
                name=op.f("fk_server_description_vendor_id_vendor"),
            ),
        )
        if not is_scd_migration()
        else ()
    )
    op.create_table(
        table_name,
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
            comment="Unique identifier, as called at the Vendor.",
        ),
        sa.Column(
            "page",
            json_type,
            nullable=False,
            comment="Detailed server description with up to 500 words total across multiple paragraphs on hardware specs, benchmark-relative performance, qualitative cost efficiency, tradeoffs, and workload fit.",
        ),
        sa.Column(
            "description",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Dense and technical server description using around 150 words in a single paragraph.",
        ),
        sa.Column(
            "og_description",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="200 character server description explicitly including vendor and server name.",
        ),
        sa.Column(
            "meta_description",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="150 character server description explicitly including vendor and server name.",
        ),
        sa.Column(
            "tagline",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="20-word tagline on server positioning and key differentiators without the vendor or server name.",
        ),
        sa.Column(
            "bullet_points",
            json_type,
            nullable=False,
            comment="4-6 concise bullet points highlighting key features and best-fit workloads.",
        ),
        sa.Column(
            "categories",
            json_type,
            nullable=False,
            comment="One or more workload categories best fitting the server.",
        ),
        sa.Column(
            "status",
            sa.dialects.postgresql.ENUM(
                "ACTIVE", "INACTIVE", name="status", create_type=False
            )
            if is_postgresql
            else sa.Enum(
                "ACTIVE",
                "INACTIVE",
                name="status",
            ),
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
        sa.PrimaryKeyConstraint(*primary_key, name=op.f(f"pk_{table_name}")),
        comment="Variable length, plain English descriptions of Server hardware specs, performance, cost-efficiency, and workflow fit."
        if not is_scd_migration()
        else "SCD version of .tables.ServerDescription.",
    )


def downgrade() -> None:
    table_name = scdize_suffix("server_description")
    op.drop_table(table_name)
