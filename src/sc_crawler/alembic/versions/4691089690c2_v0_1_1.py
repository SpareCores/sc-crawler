"""v0.1.1

Revision ID: 4691089690c2
Revises: 98894dffd37c
Create Date: 2024-04-10 00:59:03.509522

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "4691089690c2"
down_revision: Union[str, None] = "98894dffd37c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Lookup context/config attributes:
# - op.get_context().config.attributes.get("scd")


def upgrade() -> None:
    if op.get_context().config.attributes.get("scd"):
        op.alter_column(
            "server_scd", "cpu_cores", existing_type=sa.INTEGER(), nullable=True
        )
    else:
        op.alter_column(
            "server", "cpu_cores", existing_type=sa.INTEGER(), nullable=True
        )


def downgrade() -> None:
    if op.get_context().config.attributes.get("scd"):
        op.alter_column(
            "server_scd", "cpu_cores", existing_type=sa.INTEGER(), nullable=False
        )
    else:
        op.alter_column(
            "server", "cpu_cores", existing_type=sa.INTEGER(), nullable=False
        )
