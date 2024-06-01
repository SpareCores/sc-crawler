"""v1.1.4-memory-rename

Revision ID: 19b010d3acdf
Revises: c8d2054e68eb
Create Date: 2024-06-01 22:22:59.368641

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "19b010d3acdf"
down_revision: Union[str, None] = "c8d2054e68eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_context().config.attributes.get("scd"):
        op.alter_column(
            "server_scd", column_name="memory", new_column_name="memory_amount"
        )
    else:
        op.alter_column("server", column_name="memory", new_column_name="memory_amount")


def downgrade() -> None:
    if op.get_context().config.attributes.get("scd"):
        op.alter_column(
            "server_scd", column_name="memory_amount", new_column_name="memory"
        )
    else:
        op.alter_column("server", column_name="memory_amount", new_column_name="memory")
