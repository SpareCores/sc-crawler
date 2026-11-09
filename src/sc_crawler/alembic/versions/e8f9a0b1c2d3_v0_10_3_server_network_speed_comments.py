"""v0.10.3 server network speed is aggregated over all network cards

Revision ID: e8f9a0b1c2d3
Revises: 37c49fd74cce
Create Date: 2026-11-02 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "37c49fd74cce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (column, old comment, new comment)
_COMMENTS = (
    (
        "network_speed_baseline",
        "The baseline network performance (Gbps) of the network card.",
        "The baseline network performance (Gbps) of the server, aggregated over all network cards.",
    ),
    (
        "network_speed_max",
        "The maximum network performance (Gbps) of the network card.",
        "The maximum network performance (Gbps) of the server, aggregated over all network cards.",
    ),
)


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def _set_comments(new: bool) -> None:
    # SQLite does not store column comments
    if op.get_context().dialect.name != "postgresql":
        return
    for column, old_comment, new_comment in _COMMENTS:
        op.alter_column(
            scdize_suffix("server"),
            column,
            existing_type=sa.Float(),
            existing_nullable=True,
            comment=new_comment if new else old_comment,
            existing_comment=old_comment if new else new_comment,
        )


def upgrade() -> None:
    _set_comments(new=True)


def downgrade() -> None:
    _set_comments(new=False)
