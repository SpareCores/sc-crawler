"""v1.2.1 convert gpu_count from int to float

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
    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        batch_op.alter_column(
            "gpu_count",
            existing_type=sa.INTEGER(),
            type_=sa.Float(),
            existing_nullable=False,
        )


def downgrade() -> None:
    server_table_name = (
        "server_scd" if op.get_context().config.attributes.get("scd") else "server"
    )
    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        batch_op.alter_column(
            "gpu_count",
            existing_type=sa.Float(),
            type_=sa.INTEGER(),
            existing_nullable=False,
        )
