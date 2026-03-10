"""v0.3.4 convert gpu_count from int to float

Revision ID: aeae56af8ca6
Revises: dad8a1f0f455
Create Date: 2026-01-30 20:14:29.156914

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from sc_crawler.alembic.create_tables import (
    get_benchmark_table,
    get_compliance_framework_table,
    get_server_table,
    get_zone_table,
)

# revision identifiers, used by Alembic.
revision: str = "aeae56af8ca6"
down_revision: Union[str, None] = "dad8a1f0f455"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return op.get_context().config.attributes.get("scd")


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def upgrade() -> None:
    benchmark_table_name = scdize_suffix("benchmark")
    compliance_framework_table_name = scdize_suffix("compliance_framework")
    server_table_name = scdize_suffix("server")
    zone_table_name = scdize_suffix("zone")
    benchmark_table: sa.Table = get_benchmark_table(is_scd_migration())
    compliance_framework_table: sa.Table = get_compliance_framework_table(
        is_scd_migration()
    )
    server_table: sa.Table = get_server_table(is_scd_migration())
    zone_table: sa.Table = get_zone_table(is_scd_migration())
    with op.batch_alter_table(
        server_table_name,
        schema=None,
        copy_from=server_table,
    ) as batch_op:
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
    with op.batch_alter_table(
        benchmark_table_name, schema=None, copy_from=benchmark_table
    ) as batch_op:
        batch_op.alter_column(
            "measurement",
            comment="The name of measurement recorded in the benchmark.",
        )
    with op.batch_alter_table(
        zone_table_name, schema=None, copy_from=zone_table
    ) as batch_op:
        batch_op.alter_column(
            "api_reference",
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depending on the vendor and actual API endpoint.",
        )
    with op.batch_alter_table(
        compliance_framework_table_name,
        schema=None,
        copy_from=compliance_framework_table,
    ) as batch_op:
        batch_op.alter_column(
            "description",
            comment="Description of the framework in a few paragraphs, outlining key features and characteristics for reference.",
        )


def downgrade() -> None:
    benchmark_table_name = scdize_suffix("benchmark")
    compliance_framework_table_name = scdize_suffix("compliance_framework")
    server_table_name = scdize_suffix("server")
    zone_table_name = scdize_suffix("zone")
    benchmark_table: sa.Table = get_benchmark_table(is_scd_migration())
    compliance_framework_table: sa.Table = get_compliance_framework_table(
        is_scd_migration()
    )
    server_table: sa.Table = get_server_table(is_scd_migration())
    zone_table: sa.Table = get_zone_table(is_scd_migration())
    with op.batch_alter_table(
        server_table_name, schema=None, copy_from=server_table
    ) as batch_op:
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
    with op.batch_alter_table(
        benchmark_table_name, schema=None, copy_from=benchmark_table
    ) as batch_op:
        batch_op.alter_column(
            "measurement",
            comment="The name of measurement recoreded in the benchmark.",
        )
    with op.batch_alter_table(
        zone_table_name, schema=None, copy_from=zone_table
    ) as batch_op:
        batch_op.alter_column(
            "api_reference",
            comment="How this resource is referenced in the vendor API calls. This is usually either the id or name of the resource, depening on the vendor and actual API endpoint.",
        )
    with op.batch_alter_table(
        compliance_framework_table_name,
        schema=None,
        copy_from=compliance_framework_table,
    ) as batch_op:
        batch_op.alter_column(
            "description",
            comment="Description of the framework in a few paragrahs, outlining key features and characteristics for reference.",
        )
