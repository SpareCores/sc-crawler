"""v0.1.3 step #2

Revision ID: f6bf6152039a
Revises: f6edf4a96a78
Create Date: 2024-05-07 13:31:37.873389

"""

from typing import Optional, Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6bf6152039a"
down_revision: Union[str, None] = "f6edf4a96a78"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# DRY helper function
def update_api_reference_and_display_name(
    batch_op, reverse: bool = False, table: Optional[str] = None
):
    if not reverse:
        batch_op.execute(f"UPDATE {table} SET api_reference = name")
        if table == "datacenter":
            batch_op.execute(
                "UPDATE datacenter SET api_reference = datacenter_id WHERE vendor_id = 'aws'"
            )
        batch_op.execute(f"UPDATE {table} SET display_name = name")

    for col in ["api_reference", "display_name"]:
        batch_op.alter_column(
            col,
            existing_type=sqlmodel.sql.sqltypes.AutoString(),
            nullable=reverse,
        )


# need to provide the table schema for offline mode support
meta = sa.MetaData()
datacenter_table = sa.Table(
    "datacenter_scd" if op.get_context().config.attributes.get("scd") else "datacenter",
    meta,
    sa.Column("vendor_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("datacenter_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("api_reference", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("aliases", sa.JSON(), nullable=False),
    sa.Column("country_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("city", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("address_line", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("zip_code", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("lon", sa.Float(), nullable=True),
    sa.Column("lat", sa.Float(), nullable=True),
    sa.Column("founding_year", sa.Integer(), nullable=True),
    sa.Column("green_energy", sa.Boolean(), nullable=True),
    sa.Column("status", sa.Enum("ACTIVE", "INACTIVE", name="status"), nullable=False),
    sa.Column("observed_at", sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(["country_id"], ["country.country_id"]),
    sa.ForeignKeyConstraint(["vendor_id"], ["vendor.vendor_id"]),
    sa.PrimaryKeyConstraint("vendor_id", "datacenter_id", "observed_at")
    if op.get_context().config.attributes.get("scd")
    else sa.PrimaryKeyConstraint("vendor_id", "datacenter_id"),
)
zone_table = sa.Table(
    "zone_scd" if op.get_context().config.attributes.get("scd") else "zone",
    meta,
    sa.Column("vendor_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("datacenter_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("zone_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("api_reference", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
    ),
    sa.Column("observed_at", sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(
        ["vendor_id"],
        ["vendor.vendor_id"],
    ),
    sa.PrimaryKeyConstraint("vendor_id", "datacenter_id", "zone_id", "observed_at")
    if op.get_context().config.attributes.get("scd")
    else sa.PrimaryKeyConstraint("vendor_id", "datacenter_id", "zone_id"),
)
server_table = sa.Table(
    "server_scd" if op.get_context().config.attributes.get("scd") else "server",
    meta,
    sa.Column("vendor_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("server_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("api_reference", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("family", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("vcpus", sa.Integer(), nullable=False),
    sa.Column("hypervisor", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column(
        "cpu_allocation",
        sa.Enum("SHARED", "BURSTABLE", "DEDICATED", name="cpuallocation"),
        nullable=False,
    ),
    sa.Column("cpu_cores", sa.Integer(), nullable=True),
    sa.Column("cpu_speed", sa.Float(), nullable=True),
    sa.Column(
        "cpu_architecture",
        sa.Enum(
            "ARM64",
            "ARM64_MAC",
            "I386",
            "X86_64",
            "X86_64_MAC",
            name="cpuarchitecture",
        ),
        nullable=False,
    ),
    sa.Column("cpu_manufacturer", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("cpu_family", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("cpu_model", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("cpus", sa.JSON(), nullable=False),
    sa.Column("memory", sa.Integer(), nullable=False),
    sa.Column("gpu_count", sa.Integer(), nullable=False),
    sa.Column("gpu_memory_min", sa.Integer(), nullable=True),
    sa.Column("gpu_memory_total", sa.Integer(), nullable=True),
    sa.Column("gpu_manufacturer", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("gpu_model", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("gpus", sa.JSON(), nullable=False),
    sa.Column("storage_size", sa.Integer(), nullable=False),
    sa.Column(
        "storage_type",
        sa.Enum("HDD", "SSD", "NVME_SSD", "NETWORK", name="storagetype"),
    ),
    sa.Column("storages", sa.JSON(), nullable=False),
    sa.Column("network_speed", sa.Float(), nullable=True),
    sa.Column("inbound_traffic", sa.Float(), nullable=False),
    sa.Column("outbound_traffic", sa.Float(), nullable=False),
    sa.Column("ipv4", sa.Integer(), nullable=False),
    sa.Column("status", sa.Enum("ACTIVE", "INACTIVE", name="status"), nullable=False),
    sa.Column("observed_at", sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(
        ["vendor_id"],
        ["vendor.vendor_id"],
    ),
    sa.PrimaryKeyConstraint("vendor_id", "server_id", "observed_at")
    if op.get_context().config.attributes.get("scd")
    else sa.PrimaryKeyConstraint("vendor_id", "server_id"),
)


def upgrade() -> None:
    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "datacenter_scd", schema=None, copy_from=datacenter_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, table="datacenter_scd")
    else:
        with op.batch_alter_table(
            "datacenter", schema=None, copy_from=datacenter_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, table="datacenter")

    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "zone_scd", schema=None, copy_from=zone_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, table="zone_scd")
    else:
        with op.batch_alter_table(
            "zone", schema=None, copy_from=zone_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, table="zone")

    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "server_scd", schema=None, copy_from=server_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, table="server_scd")
    else:
        with op.batch_alter_table(
            "server", schema=None, copy_from=server_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, table="server")


def downgrade() -> None:
    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "datacenter_scd", schema=None, copy_from=datacenter_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, reverse=True)
    else:
        with op.batch_alter_table(
            "datacenter", schema=None, copy_from=datacenter_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, reverse=True)

    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "zone_scd", schema=None, copy_from=zone_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, reverse=True)
    else:
        with op.batch_alter_table(
            "zone", schema=None, copy_from=zone_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, reverse=True)

    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "server_scd", schema=None, copy_from=server_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, reverse=True)
    else:
        with op.batch_alter_table(
            "server", schema=None, copy_from=server_table
        ) as batch_op:
            update_api_reference_and_display_name(batch_op, reverse=True)
