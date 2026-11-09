"""v0.10.3 extend accelerator type enum with NPU, FPGA and VPU

Revision ID: c7d8e9f0a1b2
Revises: e8f9a0b1c2d3
Create Date: 2026-11-03 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = ("NPU", "FPGA", "VPU")
_OLD_VALUES = ("GPU", "TPU")

# (column, old comment, new comment) as TPUs are now stored as NPU
_SERVER_COLUMN_COMMENTS = (
    (
        "accelerator_count",
        "Number of accelerator(s), e.g. GPUs or TPUs.",
        "Number of accelerator(s), e.g. GPUs or NPUs.",
    ),
    (
        "accelerator_type",
        "The type of the primary accelerator, e.g. GPU or TPU.",
        "The type of the primary accelerator, e.g. GPU or NPU.",
    ),
)


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def upgrade() -> None:
    # other dialects store the enum as a plain string without a type to extend
    if op.get_context().dialect.name != "postgresql":
        return
    # SQLAlchemy stores AcceleratorType member names (GPU, TPU, …), not values.
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE acceleratortype ADD VALUE IF NOT EXISTS '{value}'")
    # SQLite does not store column comments
    for column, _, comment in _SERVER_COLUMN_COMMENTS:
        op.alter_column(scdize_suffix("server"), column, comment=comment)


def downgrade() -> None:
    if op.get_context().dialect.name != "postgresql":
        return

    server_table_name = scdize_suffix("server")
    for column, comment, _ in _SERVER_COLUMN_COMMENTS:
        op.alter_column(server_table_name, column, comment=comment)
    new_values = ", ".join(f"'{value}'" for value in _NEW_VALUES)
    # the new values cannot be represented by the old enum
    op.execute(
        f"""
        UPDATE {server_table_name}
        SET accelerator_type = NULL
        WHERE accelerator_type IN ({new_values})
        """  # noqa: S608
    )
    old_values = ", ".join(f"'{value}'" for value in _OLD_VALUES)
    op.execute("ALTER TYPE acceleratortype RENAME TO acceleratortype_old")
    op.execute(f"CREATE TYPE acceleratortype AS ENUM ({old_values})")
    op.execute(
        f"""
        ALTER TABLE {server_table_name}
        ALTER COLUMN accelerator_type TYPE acceleratortype
        USING accelerator_type::text::acceleratortype
        """  # noqa: S608
    )
    op.execute("DROP TYPE acceleratortype_old")
