"""v0.8.1 set server desc not nullable

Revision ID: 816a0ef08432
Revises: a1b2c3d4e5f6
Create Date: 2026-06-29 16:07:31.641782

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "816a0ef08432"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def upgrade() -> None:
    server_table_name = scdize_suffix("server")
    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        batch_op.alter_column("description", existing_type=sa.VARCHAR(), nullable=False)


def downgrade() -> None:
    server_table_name = scdize_suffix("server")
    with op.batch_alter_table(server_table_name, schema=None) as batch_op:
        batch_op.alter_column("description", existing_type=sa.VARCHAR(), nullable=True)
