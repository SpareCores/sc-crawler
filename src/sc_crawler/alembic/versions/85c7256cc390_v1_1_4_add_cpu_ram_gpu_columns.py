"""v1.1.4-add-cpu-ram-gpu-columns

Revision ID: 85c7256cc390
Revises: 19b010d3acdf
Create Date: 2024-06-01 22:47:29.563473

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "85c7256cc390"
down_revision: Union[str, None] = "19b010d3acdf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# need to provide the table schema for offline mode support
meta = sa.MetaData()
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
    sa.Column("memory_amount", sa.Integer(), nullable=False),
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
    table_name = (
        "server_scd" if op.get_context().config.attributes.get("scd") else "server"
    )
    with op.batch_alter_table(
        table_name, schema=None, copy_from=server_table, recreate="always"
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "cpu_l1_cache",
                sa.Integer(),
                nullable=True,
                comment="L1 cache size (MiB).",
            ),
            insert_after="cpu_model",
        )
        batch_op.add_column(
            sa.Column(
                "cpu_l2_cache",
                sa.Integer(),
                nullable=True,
                comment="L2 cache size (MiB).",
            ),
            insert_after="cpu_l1_cache",
        )
        batch_op.add_column(
            sa.Column(
                "cpu_l3_cache",
                sa.Integer(),
                nullable=True,
                comment="L3 cache size (MiB).",
            ),
            insert_after="cpu_l2_cache",
        )
        batch_op.add_column(
            sa.Column(
                "cpu_flags",
                sa.JSON(),
                nullable=False,
                comment="CPU features/flags.",
                default=[],
            ),
            insert_after="cpu_l3_cache",
        )
        batch_op.add_column(
            sa.Column(
                "memory_generation",
                sa.Enum("DDR3", "DDR4", "DDR5", name="ddrgeneration"),
                nullable=True,
                comment="Generation of the DDR SDRAM, e.g. DDR4 or DDR5.",
            ),
            insert_after="memory_amount",
        )
        batch_op.add_column(
            sa.Column(
                "memory_speed",
                sa.Integer(),
                nullable=True,
                comment="DDR SDRAM clock rate (Mhz).",
            ),
            insert_after="memory_generation",
        )
        batch_op.add_column(
            sa.Column(
                "memory_ecc",
                sa.Boolean(),
                nullable=True,
                comment="If the DDR SDRAM uses error correction code to detect and correct n-bit data corruption.",
            ),
            insert_after="memory_speed",
        )
        batch_op.add_column(
            sa.Column(
                "gpu_family",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=True,
                comment="The product family of the primary GPU accelerator, e.g. Turing.",
            ),
            insert_after="gpu_manufacturer",
        )


def downgrade() -> None:
    table_name = (
        "server_scd" if op.get_context().config.attributes.get("scd") else "server"
    )
    with op.batch_alter_table(table_name, schema=None) as batch_op:
        batch_op.drop_column("gpu_family")
        batch_op.drop_column("memory_ecc")
        batch_op.drop_column("memory_speed")
        batch_op.drop_column("memory_generation")
        batch_op.drop_column("cpu_flags")
        batch_op.drop_column("cpu_l3_cache")
        batch_op.drop_column("cpu_l2_cache")
        batch_op.drop_column("cpu_l1_cache")
