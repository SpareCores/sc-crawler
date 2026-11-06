"""v0.10.3 update server and database family and series column comments

Revision ID: 7e3a9c1b5d24
Revises: 37c49fd74cce
Create Date: 2026-11-06 12:00:00.000000

"""

from typing import Sequence, Union

import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7e3a9c1b5d24"
down_revision: Union[str, None] = "37c49fd74cce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


# (table, column, old comment, new comment)
_COMMENTS = (
    (
        "server",
        "family",
        "Server family, e.g. General-purpose machine (GCP), or M5g (AWS).",
        "Broad workload class of the server in the vendor's own naming, e.g. General Purpose, Compute Optimized or Memory Optimized.",
    ),
    (
        "server",
        "series",
        "Server series within the family, e.g. b3 (OVH General Purpose).",
        "Hardware line and generation of the server, e.g. m5 (AWS), n2 (GCP) or b3 (OVH).",
    ),
    (
        "database",
        "family",
        "Hardware family or class classification.",
        "Broad workload class of the database in the vendor's own naming, e.g. General Purpose or Memory Optimized.",
    ),
    (
        "database",
        "series",
        "Hardware series within the family.",
        "Hardware line and generation of the database, matching the series of the server it runs on, where known.",
    ),
)


def _set_comments(new: bool) -> None:
    # SQLite has no column comments, nothing to update there
    if op.get_context().dialect.name == "sqlite":
        return
    for table, column, old_comment, new_comment in _COMMENTS:
        op.alter_column(
            scdize_suffix(table),
            column,
            existing_type=sqlmodel.sql.sqltypes.AutoString(),
            existing_nullable=True,
            comment=new_comment if new else old_comment,
        )


def upgrade() -> None:
    _set_comments(new=True)


def downgrade() -> None:
    _set_comments(new=False)
