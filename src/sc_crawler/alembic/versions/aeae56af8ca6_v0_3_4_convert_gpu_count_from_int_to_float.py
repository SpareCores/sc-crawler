"""v0.3.4 convert gpu_count from int to float

Revision ID: aeae56af8ca6
Revises: dad8a1f0f455
Create Date: 2026-01-30 20:14:29.156914

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aeae56af8ca6"
down_revision: Union[str, None] = "dad8a1f0f455"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    server_table_name = (
        "server_scd" if op.get_context().config.attributes.get("scd") else "server"
    )
    benchmark_table_name = (
        "benchmark_scd"
        if op.get_context().config.attributes.get("scd")
        else "benchmark"
    )
    zone_table_name = (
        "zone_scd" if op.get_context().config.attributes.get("scd") else "zone"
    )
    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        batch_op.alter_column(
            "gpu_count",
            existing_type=sa.INTEGER(),
            type_=sa.Float(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "api_reference",
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depending on the vendor and actual API endpoint.",
        )
    with op.batch_alter_table(benchmark_table_name, schema=None) as batch_op:
        batch_op.alter_column(
            "measurement",
            comment="The name of measurement recorded in the benchmark.",
        )
    with op.batch_alter_table(zone_table_name, schema=None) as batch_op:
        batch_op.alter_column(
            "api_reference",
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depending on the vendor and actual API endpoint.",
        )


def downgrade() -> None:
    server_table_name = (
        "server_scd" if op.get_context().config.attributes.get("scd") else "server"
    )
    benchmark_table_name = (
        "benchmark_scd"
        if op.get_context().config.attributes.get("scd")
        else "benchmark"
    )
    zone_table_name = (
        "zone_scd" if op.get_context().config.attributes.get("scd") else "zone"
    )
    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        batch_op.alter_column(
            "gpu_count",
            existing_type=sa.Float(),
            type_=sa.INTEGER(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "api_reference",
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depening on the vendor and actual API endpoint.",
        )
    with op.batch_alter_table(benchmark_table_name, schema=None) as batch_op:
        batch_op.alter_column(
            "measurement",
            comment="The name of measurement recoreded in the benchmark.",
        )
    with op.batch_alter_table(zone_table_name, schema=None) as batch_op:
        batch_op.alter_column(
            "api_reference",
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depening on the vendor and actual API endpoint.",
        )
