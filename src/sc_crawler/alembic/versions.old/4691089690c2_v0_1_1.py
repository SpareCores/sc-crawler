"""v0.1.1

Revision ID: 4691089690c2
Revises: 98894dffd37c
Create Date: 2024-04-10 00:59:03.509522

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4691089690c2"
down_revision: Union[str, None] = "98894dffd37c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


## need to provide the table schema for offline mode support
meta = sa.MetaData()
server_table = sa.Table(
    "server_scd" if op.get_context().config.attributes.get("scd") else "server",
    meta,
    sa.Column(
        "vendor_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
    ),
    sa.Column(
        "server_id",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
    ),
    sa.Column(
        "name",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=False,
    ),
    sa.Column(
        "vcpus",
        sa.Integer(),
        nullable=False,
    ),
    sa.Column(
        "hypervisor",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
    ),
    sa.Column(
        "cpu_allocation",
        sa.Enum("SHARED", "BURSTABLE", "DEDICATED", name="cpuallocation"),
        nullable=False,
    ),
    sa.Column(
        "cpu_cores",
        sa.Integer(),
        nullable=False,
    ),
    sa.Column(
        "cpu_speed",
        sa.Float(),
        nullable=True,
    ),
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
    sa.Column(
        "cpu_manufacturer",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
    ),
    sa.Column(
        "cpu_family",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
    ),
    sa.Column(
        "cpu_model",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
    ),
    sa.Column(
        "cpus",
        sa.JSON(),
        nullable=False,
    ),
    sa.Column("memory", sa.Integer(), nullable=False),
    sa.Column(
        "gpu_count",
        sa.Integer(),
        nullable=False,
    ),
    sa.Column(
        "gpu_memory_min",
        sa.Integer(),
        nullable=True,
    ),
    sa.Column(
        "gpu_memory_total",
        sa.Integer(),
        nullable=True,
    ),
    sa.Column(
        "gpu_manufacturer",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
    ),
    sa.Column(
        "gpu_model",
        sqlmodel.sql.sqltypes.AutoString(),
        nullable=True,
    ),
    sa.Column(
        "gpus",
        sa.JSON(),
        nullable=False,
    ),
    sa.Column(
        "storage_size",
        sa.Integer(),
        nullable=False,
    ),
    sa.Column(
        "storage_type",
        sa.Enum("HDD", "SSD", "NVME_SSD", "NETWORK", name="storagetype"),
        nullable=True,
    ),
    sa.Column(
        "storages",
        sa.JSON(),
        nullable=False,
    ),
    sa.Column(
        "network_speed",
        sa.Float(),
        nullable=True,
    ),
    sa.Column(
        "inbound_traffic",
        sa.Float(),
        nullable=False,
    ),
    sa.Column(
        "outbound_traffic",
        sa.Float(),
        nullable=False,
    ),
    sa.Column(
        "ipv4",
        sa.Integer(),
        nullable=False,
    ),
    sa.Column(
        "status",
        sa.Enum("ACTIVE", "INACTIVE", name="status"),
        nullable=False,
    ),
    sa.Column(
        "observed_at",
        sa.DateTime(),
        nullable=False,
    ),
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
            "server_scd", schema=None, copy_from=server_table
        ) as batch_op:
            batch_op.alter_column(
                "cpu_cores", existing_type=sa.INTEGER(), nullable=True
            )
            batch_op.add_column(
                sa.Column(
                    "description",
                    sqlmodel.sql.sqltypes.AutoString(),
                    nullable=True,
                    comment="Short description.",
                )
            )
    else:
        with op.batch_alter_table(
            "server", schema=None, copy_from=server_table
        ) as batch_op:
            batch_op.alter_column(
                "cpu_cores", existing_type=sa.INTEGER(), nullable=True
            )
            batch_op.add_column(
                sa.Column(
                    "description",
                    sqlmodel.sql.sqltypes.AutoString(),
                    nullable=True,
                    comment="Short description.",
                )
            )


def downgrade() -> None:
    server_table.append_column(
        sa.Column(
            "description",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Short description.",
        )
    )
    if op.get_context().config.attributes.get("scd"):
        with op.batch_alter_table(
            "server_scd", schema=None, copy_from=server_table
        ) as batch_op:
            batch_op.alter_column(
                "cpu_cores", existing_type=sa.INTEGER(), nullable=False
            )
            batch_op.drop_column("description")
    else:
        with op.batch_alter_table(
            "server", schema=None, copy_from=server_table
        ) as batch_op:
            batch_op.alter_column(
                "cpu_cores", existing_type=sa.INTEGER(), nullable=False
            )
            batch_op.drop_column("description")
