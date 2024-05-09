"""v0.1.3 step #1

Revision ID: f6edf4a96a78
Revises: 4691089690c2
Create Date: 2024-05-07 13:31:37.873389

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6edf4a96a78"
down_revision: Union[str, None] = "4691089690c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# DRY helper function
def add_api_reference_and_display_name(batch_op):
    # need to add as nullable first, then set values, and update to nullable in followup migration step
    batch_op.add_column(
        sa.Column(
            "api_reference",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depening on the vendor and actual API endpoint.",
        ),
        insert_after="name",  # TODO all other
    )
    batch_op.add_column(
        sa.Column(
            "display_name",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Human-friendly reference (usually the id or name) of the resource.",
        ),
        insert_after="api_reference",
    )


# need to provide the table schema for offline mode support
meta = sa.MetaData()
enum_status = sa.Enum("ACTIVE", "INACTIVE", name="status").with_variant(
    sa.dialects.postgresql.ENUM("ACTIVE", "INACTIVE", name="status", create_type=False),
    "postgresql",
)
enum_cpuallocation = sa.Enum(
    "SHARED", "BURSTABLE", "DEDICATED", name="cpuallocation"
).with_variant(
    sa.dialects.postgresql.ENUM(
        "SHARED", "BURSTABLE", "DEDICATED", name="cpuallocation", create_type=False
    ),
    "postgresql",
)
enum_cpuarchitecture = sa.Enum(
    "ARM64", "ARM64_MAC", "I386", "X86_64", "X86_64_MAC", name="cpuarchitecture"
).with_variant(
    sa.dialects.postgresql.ENUM(
        "ARM64",
        "ARM64_MAC",
        "I386",
        "X86_64",
        "X86_64_MAC",
        name="cpuarchitecture",
        create_type=False,
    ),
    "postgresql",
)
enum_storage_type = enum_storage_type = sa.Enum(
    "HDD", "SSD", "NVME_SSD", "NETWORK", name="storagetype"
).with_variant(
    sa.dialects.postgresql.ENUM(
        "HDD",
        "SSD",
        "NVME_SSD",
        "NETWORK",
        name="storagetype",
        create_type=False,
    ),
    "postgresql",
)
datacenter_table = sa.Table(
    "datacenter_scd" if op.get_context().config.attributes.get("scd") else "datacenter",
    meta,
    sa.Column("vendor_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("datacenter_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("aliases", sa.JSON(), nullable=False),
    sa.Column("country_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("city", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("address_line", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("zip_code", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("founding_year", sa.Integer(), nullable=True),
    sa.Column("green_energy", sa.Boolean(), nullable=True),
    sa.Column("status", enum_status, nullable=False),
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
    sa.Column("status", enum_status, nullable=False),
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
    sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("vcpus", sa.Integer(), nullable=False),
    sa.Column("hypervisor", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column("cpu_allocation", enum_cpuallocation, nullable=False),
    sa.Column("cpu_cores", sa.Integer(), nullable=True),
    sa.Column("cpu_speed", sa.Float(), nullable=True),
    sa.Column("cpu_architecture", enum_cpuarchitecture, nullable=False),
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
    sa.Column("storage_type", enum_storage_type),
    sa.Column("storages", sa.JSON(), nullable=False),
    sa.Column("network_speed", sa.Float(), nullable=True),
    sa.Column("inbound_traffic", sa.Float(), nullable=False),
    sa.Column("outbound_traffic", sa.Float(), nullable=False),
    sa.Column("ipv4", sa.Integer(), nullable=False),
    sa.Column("status", enum_status, nullable=False),
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
            "datacenter_scd", schema=None, copy_from=datacenter_table, recreate="always"
        ) as batch_op:
            add_api_reference_and_display_name(batch_op)
            batch_op.add_column(
                sa.Column(
                    "lon",
                    sa.Float(),
                    nullable=True,
                    comment="Longitude coordinate of the Datacenter's known or approximate location.",
                )
            )
            batch_op.add_column(
                sa.Column(
                    "lat",
                    sa.Float(),
                    nullable=True,
                    comment="Latitude coordinate of the Datacenter's known or approximate location.",
                )
            )
    else:
        with op.batch_alter_table(
            "datacenter", schema=None, copy_from=datacenter_table, recreate="always"
        ) as batch_op:
            add_api_reference_and_display_name(batch_op)
            batch_op.add_column(
                sa.Column(
                    "lon",
                    sa.Float(),
                    nullable=True,
                    comment="Longitude coordinate of the Datacenter's known or approximate location.",
                ),
                insert_after="zip_code",
            )
            batch_op.add_column(
                sa.Column(
                    "lat",
                    sa.Float(),
                    nullable=True,
                    comment="Latitude coordinate of the Datacenter's known or approximate location.",
                ),
                insert_after="lon",
            )

    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "zone_scd", schema=None, copy_from=zone_table, recreate="always"
        ) as batch_op:
            add_api_reference_and_display_name(batch_op)
    else:
        with op.batch_alter_table(
            "zone", schema=None, copy_from=zone_table, recreate="always"
        ) as batch_op:
            add_api_reference_and_display_name(batch_op)

    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "server_scd", schema=None, copy_from=server_table, recreate="always"
        ) as batch_op:
            add_api_reference_and_display_name(batch_op)
            batch_op.add_column(
                sa.Column(
                    "family",
                    sqlmodel.sql.sqltypes.AutoString(),
                    nullable=True,
                    comment="Server family, e.g. General-purpose machine (GCP), or M5g (AWS).",
                ),
                insert_before="vcpus",
            )
    else:
        with op.batch_alter_table(
            "server", schema=None, copy_from=server_table, recreate="always"
        ) as batch_op:
            add_api_reference_and_display_name(batch_op)
            batch_op.add_column(
                sa.Column(
                    "family",
                    sqlmodel.sql.sqltypes.AutoString(),
                    nullable=True,
                    comment="Server family, e.g. General-purpose machine (GCP), or M5g (AWS).",
                ),
                insert_before="vcpus",
            )


def downgrade() -> None:
    datacenter_table.append_column(
        sa.Column("api_reference", sqlmodel.sql.sqltypes.AutoString())
    )
    datacenter_table.append_column(
        sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString())
    )
    datacenter_table.append_column(sa.Column("lon", sa.Float(), nullable=True))
    datacenter_table.append_column(sa.Column("lat", sa.Float(), nullable=True))
    zone_table.append_column(
        sa.Column("api_reference", sqlmodel.sql.sqltypes.AutoString())
    )
    zone_table.append_column(
        sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString())
    )
    server_table.append_column(
        sa.Column("api_reference", sqlmodel.sql.sqltypes.AutoString())
    )
    server_table.append_column(
        sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString())
    )
    server_table.append_column(
        sa.Column("family", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
    )

    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "datacenter_scd", schema=None, copy_from=datacenter_table
        ) as batch_op:
            batch_op.drop_column("api_reference")
            batch_op.drop_column("display_name")
            batch_op.drop_column("lon")
            batch_op.drop_column("lat")
    else:
        with op.batch_alter_table(
            "datacenter", schema=None, copy_from=datacenter_table
        ) as batch_op:
            batch_op.drop_column("api_reference")
            batch_op.drop_column("display_name")
            batch_op.drop_column("lon")
            batch_op.drop_column("lat")

    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "zone_scd", schema=None, copy_from=zone_table
        ) as batch_op:
            batch_op.drop_column("api_reference")
            batch_op.drop_column("display_name")
    else:
        with op.batch_alter_table(
            "zone", schema=None, copy_from=zone_table
        ) as batch_op:
            batch_op.drop_column("api_reference")
            batch_op.drop_column("display_name")

    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "server_scd", schema=None, copy_from=server_table
        ) as batch_op:
            batch_op.drop_column("family")
            batch_op.drop_column("display_name")
            batch_op.drop_column("api_reference")
    else:
        with op.batch_alter_table(
            "server", schema=None, copy_from=server_table
        ) as batch_op:
            batch_op.drop_column("family")
            batch_op.drop_column("display_name")
            batch_op.drop_column("api_reference")
