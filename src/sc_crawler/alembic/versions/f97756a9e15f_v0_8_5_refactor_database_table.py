"""v0.8.5 refactor database table

Revision ID: f97756a9e15f
Revises: d5e6f7a8b9c0
Create Date: 2026-07-29 23:22:23.279088

"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f97756a9e15f"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def _enum(name: str, values: tuple[str, ...]):
    is_postgresql = op.get_context().dialect.name == "postgresql"
    if is_postgresql:
        return sa.dialects.postgresql.ENUM(*values, name=name, create_type=False)
    return sa.Enum(*values, name=name)


_HA_LEVEL_VALUES = ("NONE", "SINGLE_ZONE", "MULTI_ZONE", "MULTI_REGION")
_HA_STRATEGY_VALUES = ("NONE", "PASSIVE_STANDBY", "READABLE_CLUSTER", "MULTI_MASTER")


def _ha_rank_sql(column: str) -> str:
    """CASE expression: lower rank = lower HA tier (preferred on downgrade)."""
    # Match both enum names (Postgres) and values (possible on SQLite).
    mapping = (
        ("NONE", "none", 0),
        ("SINGLE_ZONE", "single-zone", 1),
        ("MULTI_ZONE", "multi-zone", 2),
        ("MULTI_REGION", "multi-region", 3),
    )
    whens = " ".join(
        f"WHEN '{name}' THEN {rank} WHEN '{value}' THEN {rank}"
        for name, value, rank in mapping
    )
    return f"CASE CAST({column} AS TEXT) {whens} ELSE 4 END"


def _ha_strategy_rank_sql(column: str) -> str:
    """CASE expression: lower rank = lower HA strategy tier."""
    mapping = (
        ("NONE", "none", 0),
        ("PASSIVE_STANDBY", "passive-standby", 1),
        ("READABLE_CLUSTER", "readable-cluster", 2),
        ("MULTI_MASTER", "multi-master", 3),
    )
    whens = " ".join(
        f"WHEN '{name}' THEN {rank} WHEN '{value}' THEN {rank}"
        for name, value, rank in mapping
    )
    return f"CASE CAST({column} AS TEXT) {whens} ELSE 4 END"


def _dedupe_database_price_for_pre_v085_pk(table_name: str, is_scd: bool) -> None:
    """Keep one row per pre-v0.8.5 PK: lowest ha, then lowest ha_strategy."""
    partition = "vendor_id, region_id, database_id, allocation"
    if is_scd:
        partition = f"{partition}, observed_at"
    is_postgresql = op.get_context().dialect.name == "postgresql"
    row_id = "ctid" if is_postgresql else "rowid"
    ha_rank = _ha_rank_sql("ha")
    strategy_rank = _ha_strategy_rank_sql("ha_strategy")
    op.execute(
        sa.text(
            f"""
            DELETE FROM {table_name}
            WHERE {row_id} IN (
                SELECT {row_id} FROM (
                    SELECT {row_id},
                           ROW_NUMBER() OVER (
                               PARTITION BY {partition}
                               ORDER BY {ha_rank}, {strategy_rank}, {row_id}
                           ) AS rn
                    FROM {table_name}
                ) ranked
                WHERE rn > 1
            )
            """
        )
    )


def get_database_table(is_scd: bool) -> sa.Table:
    """Pre-v0.8.5 ``database`` / ``database_scd`` schema (copy_from source)."""
    is_postgresql = op.get_context().dialect.name == "postgresql"
    table_name = scdize_suffix("database")
    vendor_table = scdize_suffix("vendor")
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    primary_keys = (
        ("vendor_id", "database_id", "observed_at")
        if is_scd
        else ("vendor_id", "database_id")
    )
    foreign_keys = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table}"),
            ),
        )
        if not is_scd
        else ()
    )
    return sa.Table(
        table_name,
        sa.MetaData(),
        sa.Column(
            "vendor_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Reference to the Vendor.",
        ),
        sa.Column(
            "database_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Unique identifier, as called at the Vendor.",
        ),
        sa.Column(
            "name",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Human-friendly name.",
        ),
        sa.Column(
            "api_reference",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment=(
                "How this resource is referenced in the vendor API calls. "
                "This is usually either the id or name of the resource, "
                "depending on the vendor and actual API endpoint."
            ),
        ),
        sa.Column(
            "display_name",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            comment="Human-friendly reference (usually the id or name) of the resource.",
        ),
        sa.Column(
            "description",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Short description.",
        ),
        sa.Column(
            "server_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Optional reference to a related Server SKU.",
        ),
        sa.Column(
            "engine",
            _enum("databaseengine", ("POSTGRESQL",)),
            nullable=False,
            comment="Managed database engine.",
        ),
        sa.Column(
            "engine_versions",
            json_type(),
            nullable=False,
            comment="Supported major engine versions merged onto the SKU row.",
        ),
        sa.Column(
            "family",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
            comment="Database series or plan family slug.",
        ),
        sa.Column(
            "vcpus",
            sa.Integer(),
            nullable=True,
            comment="Number of virtual CPUs (vCPU) of the database SKU.",
        ),
        sa.Column(
            "memory_amount",
            sa.Integer(),
            nullable=True,
            comment="RAM amount (MiB) reported by the vendor.",
        ),
        sa.Column(
            "storage_size",
            sa.Integer(),
            nullable=True,
            comment="Bundled storage size (GB), when included in the SKU.",
        ),
        sa.Column(
            "ha_supported",
            sa.Boolean(),
            nullable=True,
            comment="If high availability is supported for the SKU.",
        ),
        sa.Column(
            "storage_autoscaling",
            sa.Boolean(),
            nullable=True,
            comment="If storage can be expanded beyond the bundled minimum.",
        ),
        sa.Column(
            "scheduled_backups",
            sa.Boolean(),
            nullable=True,
            comment="If scheduled/automated snapshot backups are supported.",
        ),
        sa.Column(
            "continuous_backups",
            sa.Integer(),
            nullable=True,
            comment="Point-in-time recovery retention in days.",
        ),
        sa.Column(
            "engine_auto_upgrade",
            sa.Boolean(),
            nullable=True,
            comment="If automatic engine version upgrades are supported.",
        ),
        sa.Column(
            "autotuning",
            sa.Boolean(),
            nullable=True,
            comment="If vendor autotuning is available.",
        ),
        sa.Column(
            "custom_config",
            sa.Boolean(),
            nullable=True,
            comment="If custom configuration parameters are supported.",
        ),
        sa.Column(
            "custom_extensions",
            sa.Boolean(),
            nullable=True,
            comment="If custom extensions are supported.",
        ),
        sa.Column(
            "support_level",
            _enum("databasesupportlevel", ("STANDARD",)),
            nullable=True,
            comment="Vendor support tier for the SKU.",
        ),
        sa.Column(
            "sla",
            sa.Float(),
            nullable=True,
            comment="Service level agreement as a percentage, e.g. 99.95.",
        ),
        sa.Column(
            "status",
            _enum("status", ("ACTIVE", "INACTIVE")),
            nullable=False,
            comment="Status of the resource (active or inactive).",
        ),
        sa.Column(
            "observed_at",
            sa.DateTime(),
            nullable=False,
            comment="Timestamp of the last observation.",
        ),
        *foreign_keys,
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
        comment="Managed database SKUs."
        if not is_scd
        else "SCD version of .tables.Database.",
    )


def get_database_price_table(is_scd: bool) -> sa.Table:
    """Pre-v0.8.5 ``database_price`` schema (copy_from source)."""
    table_name = scdize_suffix("database_price")
    vendor_table = scdize_suffix("vendor")
    region_table = scdize_suffix("region")
    database_table = scdize_suffix("database")
    primary_keys = (
        ("vendor_id", "region_id", "database_id", "allocation", "observed_at")
        if is_scd
        else ("vendor_id", "region_id", "database_id", "allocation")
    )
    foreign_keys = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "region_id"],
                [f"{region_table}.vendor_id", f"{region_table}.region_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{region_table}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "database_id"],
                [f"{database_table}.vendor_id", f"{database_table}.database_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{database_table}"),
            ),
        )
        if not is_scd
        else ()
    )
    return sa.Table(
        table_name,
        sa.MetaData(),
        sa.Column("vendor_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("region_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("database_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "allocation",
            _enum("allocation", ("ONDEMAND", "RESERVED", "SPOT")),
            nullable=False,
        ),
        sa.Column(
            "unit",
            _enum(
                "priceunit",
                ("YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH"),
            ),
            nullable=False,
        ),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("price_upfront", sa.Float(), nullable=False),
        sa.Column("price_tiered", sa.JSON(), nullable=False),
        sa.Column("currency", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", _enum("status", ("ACTIVE", "INACTIVE")), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        *foreign_keys,
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
    )


def upgrade() -> None:
    is_scd = is_scd_migration()
    is_postgresql = op.get_context().dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    database_table_name = scdize_suffix("database")
    database_table = get_database_table(is_scd)
    database_price_table_name = scdize_suffix("database_price")
    database_price_table = get_database_price_table(is_scd)
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd

    # Columns dropped: type change (ha_supported → ha JSON) or removed (support_level).
    # Columns renamed in place to preserve data.
    # Kept columns: alter comment/nullability only (no drop+readd).
    # Recreate path uses partial_reordering so CREATE TABLE order matches the model
    # while INSERT still copies by column key (renames keep the old key).
    _kept_column_comments = (
        ("family", "Hardware family or class classification."),
        ("server_id", "Reference to the underlying cloud server's identifier."),
        (
            "vcpus",
            "Number of virtual CPU cores allocated to the database server instance.",
        ),
        ("memory_amount", "Amount of RAM (MiB) provisioned for the instance."),
        ("engine_versions", "Major database engine versions supported."),
        ("storage_size", "Bundled storage capacity included in the database (GB)."),
        (
            "scheduled_backups",
            "Support for automated snapshot schedules and backup retention management.",
        ),
        (
            "continuous_backups",
            "Maximum point-in-time recovery (PITR) log retention window "
            "expressed in days (0 if unsupported).",
        ),
        (
            "custom_config",
            "Whether database engine parameters/flags can be customized.",
        ),
        (
            "custom_extensions",
            "Support for custom database engine extensions/plugins.",
        ),
        ("sla", "Service level agreement as a percentage, e.g. 99.95."),
    )
    _new_database_columns = (
        (
            "api_reference_object",
            json_type(),
            True,
            None,
            "How this resource is referenced in the vendor API calls, "
            "including the parameter name(s).",
        ),
        (
            "wire_protocol",
            sa.Enum("POSTGRESQL", name="databasewireprotocol"),
            True,
            None,
            "Network protocol used for client connections.",
        ),
        (
            "ha",
            json_type(),
            False,
            '["none"]',
            "Ordered HA levels supported, highest tier first.",
        ),
        (
            "ha_strategy",
            json_type(),
            False,
            '["none"]',
            "Ordered HA strategies supported, highest tier first.",
        ),
        (
            "max_read_replicas",
            sa.Integer(),
            True,
            None,
            "Maximum number of read-only replica nodes supported "
            "to scale read workloads.",
        ),
        (
            "storage_extra_min",
            sa.Integer(),
            True,
            None,
            "Minimum custom storage size (in GB) that can be attached to the instance.",
        ),
        (
            "storage_extra_max",
            sa.Integer(),
            True,
            None,
            "Maximum storage limit (in GB) supported by the instance or storage tier.",
        ),
        (
            "disk_encryption",
            sa.Boolean(),
            True,
            None,
            "Indicates whether underlying storage drives are encrypted at rest.",
        ),
        (
            "connection_pool",
            sa.Boolean(),
            True,
            None,
            "Managed connection proxy support.",
        ),
        (
            "system_monitoring",
            sa.Boolean(),
            True,
            None,
            "Availability of host-level CPU, RAM, and disk metrics dashboards.",
        ),
        (
            "database_monitoring",
            sa.Boolean(),
            True,
            None,
            "Database engine performance insights "
            "(slow queries, locks, execution plans).",
        ),
        (
            "autotuning_apply",
            sa.Boolean(),
            True,
            None,
            "System automatically executes performance fixes "
            "(e.g., index creation, parameter tuning) without "
            "operator intervention.",
        ),
        (
            "security_features",
            json_type(),
            False,
            "[]",
            "Security capabilities supported by DBaaS providers.",
        ),
    )
    # Keys are pre-rename names for existing cols; new cols use their final names.
    _upgrade_column_order = (
        "vendor_id",
        "database_id",
        "name",
        "api_reference",
        "api_reference_object",
        "display_name",
        "description",
        "family",
        "server_id",
        "vcpus",
        "memory_amount",
        "engine",
        "wire_protocol",
        "engine_versions",
        "engine_auto_upgrade",  # → auto_upgrade_versions
        "ha",
        "ha_strategy",
        "max_read_replicas",
        "custom_config",
        "custom_extensions",
        "storage_size",
        "storage_extra_min",
        "storage_extra_max",
        "storage_autoscaling",  # → storage_extra_autosize
        "disk_encryption",
        "scheduled_backups",
        "continuous_backups",
        "connection_pool",
        "system_monitoring",
        "database_monitoring",
        "autotuning",  # → autotuning_advice
        "autotuning_apply",
        "sla",
        "security_features",
        "status",
        "observed_at",
    )

    if do_recreate_tables:
        with op.batch_alter_table(
            database_table_name,
            schema=None,
            copy_from=database_table,
            recreate="always",
            partial_reordering=[_upgrade_column_order],
        ) as batch_op:
            for col in ("ha_supported", "support_level"):
                batch_op.drop_column(col)

            batch_op.alter_column(
                "storage_autoscaling",
                new_column_name="storage_extra_autosize",
                comment=(
                    "Whether storage capacity can automatically expand as "
                    "disk usage grows."
                ),
            )
            batch_op.alter_column(
                "engine_auto_upgrade",
                new_column_name="auto_upgrade_versions",
                comment="Auto-upgrade between minor database engine versions.",
            )
            batch_op.alter_column(
                "autotuning",
                new_column_name="autotuning_advice",
                comment=(
                    "Analyzes workload and generates actionable performance "
                    "tuning advice."
                ),
            )
            batch_op.alter_column(
                "engine",
                nullable=True,
                comment="Managed database engine running on the instance.",
            )
            for column, comment in _kept_column_comments:
                batch_op.alter_column(column, comment=comment)

            for (
                name,
                coltype,
                nullable,
                server_default,
                comment,
            ) in _new_database_columns:
                kwargs = {"nullable": nullable, "comment": comment}
                if server_default is not None:
                    kwargs["server_default"] = server_default
                batch_op.add_column(sa.Column(name, coltype, **kwargs))
    else:
        op.drop_column(database_table_name, "ha_supported")
        op.drop_column(database_table_name, "support_level")

        if is_postgresql:
            bind = op.get_bind()
            sa.Enum("POSTGRESQL", name="databasewireprotocol").create(
                bind, checkfirst=True
            )

        op.alter_column(
            database_table_name,
            "storage_autoscaling",
            new_column_name="storage_extra_autosize",
            comment=(
                "Whether storage capacity can automatically expand as disk usage grows."
            ),
        )
        op.alter_column(
            database_table_name,
            "engine_auto_upgrade",
            new_column_name="auto_upgrade_versions",
            comment="Auto-upgrade between minor database engine versions.",
        )
        op.alter_column(
            database_table_name,
            "autotuning",
            new_column_name="autotuning_advice",
            comment=(
                "Analyzes workload and generates actionable performance tuning advice."
            ),
        )
        op.alter_column(
            database_table_name,
            "engine",
            nullable=True,
            comment="Managed database engine running on the instance.",
        )
        for column, comment in _kept_column_comments:
            op.alter_column(database_table_name, column, comment=comment)

        for name, coltype, nullable, server_default, comment in _new_database_columns:
            kwargs = {"nullable": nullable, "comment": comment}
            if server_default is not None:
                kwargs["server_default"] = server_default
            op.add_column(
                database_table_name,
                sa.Column(name, coltype, **kwargs),
            )

    if is_postgresql:
        sa.Enum(name="databasesupportlevel").drop(op.get_bind(), checkfirst=True)

    database_price_pk = (
        (
            "vendor_id",
            "region_id",
            "database_id",
            "allocation",
            "ha",
            "ha_strategy",
            "observed_at",
        )
        if is_scd
        else (
            "vendor_id",
            "region_id",
            "database_id",
            "allocation",
            "ha",
            "ha_strategy",
        )
    )

    if is_postgresql:
        bind = op.get_bind()
        sa.Enum(*_HA_LEVEL_VALUES, name="databasehalevel").create(bind, checkfirst=True)
        sa.Enum(*_HA_STRATEGY_VALUES, name="databasehastrategy").create(
            bind, checkfirst=True
        )

    if do_recreate_tables:
        with op.batch_alter_table(
            database_price_table_name,
            schema=None,
            copy_from=database_price_table,
            recreate="always",
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "ha",
                    _enum("databasehalevel", _HA_LEVEL_VALUES),
                    nullable=False,
                    server_default="NONE",
                    comment="HA level this price applies to.",
                ),
                insert_after="allocation",
            )
            batch_op.add_column(
                sa.Column(
                    "ha_strategy",
                    _enum("databasehastrategy", _HA_STRATEGY_VALUES),
                    nullable=False,
                    server_default="NONE",
                    comment="HA strategy this price applies to.",
                ),
                insert_after="ha",
            )
            batch_op.drop_constraint(
                op.f(f"pk_{database_price_table_name}"), type_="primary"
            )
            batch_op.create_primary_key(
                op.f(f"pk_{database_price_table_name}"), list(database_price_pk)
            )
    else:
        op.add_column(
            database_price_table_name,
            sa.Column(
                "ha",
                _enum("databasehalevel", _HA_LEVEL_VALUES),
                nullable=False,
                server_default="NONE",
                comment="HA level this price applies to.",
            ),
        )
        op.add_column(
            database_price_table_name,
            sa.Column(
                "ha_strategy",
                _enum("databasehastrategy", _HA_STRATEGY_VALUES),
                nullable=False,
                server_default="NONE",
                comment="HA strategy this price applies to.",
            ),
        )
        op.drop_constraint(
            op.f(f"pk_{database_price_table_name}"),
            database_price_table_name,
            type_="primary",
        )
        op.create_primary_key(
            op.f(f"pk_{database_price_table_name}"),
            database_price_table_name,
            list(database_price_pk),
        )

    # SQLite cannot DROP DEFAULT via ALTER COLUMN; leave the migration default there.
    if is_postgresql:
        op.alter_column(
            database_price_table_name,
            "ha",
            server_default=None,
            existing_nullable=False,
        )
        op.alter_column(
            database_price_table_name,
            "ha_strategy",
            server_default=None,
            existing_nullable=False,
        )


def get_database_table_v085(is_scd: bool) -> sa.Table:
    """Post-v0.8.5 ``database`` schema (downgrade copy_from source)."""
    is_postgresql = op.get_context().dialect.name == "postgresql"
    table_name = scdize_suffix("database")
    vendor_table = scdize_suffix("vendor")
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
    primary_keys = (
        ("vendor_id", "database_id", "observed_at")
        if is_scd
        else ("vendor_id", "database_id")
    )
    foreign_keys = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table}"),
            ),
        )
        if not is_scd
        else ()
    )
    return sa.Table(
        table_name,
        sa.MetaData(),
        sa.Column("vendor_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("database_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("api_reference", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("api_reference_object", json_type(), nullable=True),
        sa.Column("display_name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("family", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("server_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("vcpus", sa.Integer(), nullable=True),
        sa.Column("memory_amount", sa.Integer(), nullable=True),
        sa.Column("engine", _enum("databaseengine", ("POSTGRESQL",)), nullable=True),
        sa.Column(
            "wire_protocol",
            _enum("databasewireprotocol", ("POSTGRESQL",)),
            nullable=True,
        ),
        sa.Column("engine_versions", json_type(), nullable=False),
        sa.Column("auto_upgrade_versions", sa.Boolean(), nullable=True),
        sa.Column("ha", json_type(), nullable=False),
        sa.Column("ha_strategy", json_type(), nullable=False),
        sa.Column("max_read_replicas", sa.Integer(), nullable=True),
        sa.Column("custom_config", sa.Boolean(), nullable=True),
        sa.Column("custom_extensions", sa.Boolean(), nullable=True),
        sa.Column("storage_size", sa.Integer(), nullable=True),
        sa.Column("storage_extra_min", sa.Integer(), nullable=True),
        sa.Column("storage_extra_max", sa.Integer(), nullable=True),
        sa.Column("storage_extra_autosize", sa.Boolean(), nullable=True),
        sa.Column("disk_encryption", sa.Boolean(), nullable=True),
        sa.Column("scheduled_backups", sa.Boolean(), nullable=True),
        sa.Column("continuous_backups", sa.Integer(), nullable=True),
        sa.Column("connection_pool", sa.Boolean(), nullable=True),
        sa.Column("system_monitoring", sa.Boolean(), nullable=True),
        sa.Column("database_monitoring", sa.Boolean(), nullable=True),
        sa.Column("autotuning_advice", sa.Boolean(), nullable=True),
        sa.Column("autotuning_apply", sa.Boolean(), nullable=True),
        sa.Column("sla", sa.Float(), nullable=True),
        sa.Column("security_features", json_type(), nullable=False),
        sa.Column("status", _enum("status", ("ACTIVE", "INACTIVE")), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        *foreign_keys,
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
    )


def get_database_price_table_v085(is_scd: bool) -> sa.Table:
    """Post-v0.8.5 ``database_price`` schema (downgrade copy_from source)."""
    table_name = scdize_suffix("database_price")
    vendor_table = scdize_suffix("vendor")
    region_table = scdize_suffix("region")
    database_table = scdize_suffix("database")
    primary_keys = (
        (
            "vendor_id",
            "region_id",
            "database_id",
            "allocation",
            "ha",
            "ha_strategy",
            "observed_at",
        )
        if is_scd
        else (
            "vendor_id",
            "region_id",
            "database_id",
            "allocation",
            "ha",
            "ha_strategy",
        )
    )
    foreign_keys = (
        (
            sa.ForeignKeyConstraint(
                ["vendor_id"],
                [f"{vendor_table}.vendor_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{vendor_table}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "region_id"],
                [f"{region_table}.vendor_id", f"{region_table}.region_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{region_table}"),
            ),
            sa.ForeignKeyConstraint(
                ["vendor_id", "database_id"],
                [f"{database_table}.vendor_id", f"{database_table}.database_id"],
                name=op.f(f"fk_{table_name}_vendor_id_{database_table}"),
            ),
        )
        if not is_scd
        else ()
    )
    return sa.Table(
        table_name,
        sa.MetaData(),
        sa.Column("vendor_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("region_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("database_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "allocation",
            _enum("allocation", ("ONDEMAND", "RESERVED", "SPOT")),
            nullable=False,
        ),
        sa.Column(
            "ha",
            _enum("databasehalevel", _HA_LEVEL_VALUES),
            nullable=False,
        ),
        sa.Column(
            "ha_strategy",
            _enum("databasehastrategy", _HA_STRATEGY_VALUES),
            nullable=False,
        ),
        sa.Column(
            "unit",
            _enum(
                "priceunit",
                ("YEAR", "MONTH", "HOUR", "GIB", "GB", "GB_MONTH"),
            ),
            nullable=False,
        ),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("price_upfront", sa.Float(), nullable=False),
        sa.Column("price_tiered", sa.JSON(), nullable=False),
        sa.Column("currency", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", _enum("status", ("ACTIVE", "INACTIVE")), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        *foreign_keys,
        sa.PrimaryKeyConstraint(*primary_keys, name=op.f(f"pk_{table_name}")),
    )


def downgrade() -> None:
    is_scd = is_scd_migration()
    is_postgresql = op.get_context().dialect.name == "postgresql"
    database_table_name = scdize_suffix("database")
    database_table = get_database_table_v085(is_scd)
    database_price_table_name = scdize_suffix("database_price")
    database_price_table = get_database_price_table_v085(is_scd)
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd
    database_price_pk = (
        ("vendor_id", "region_id", "database_id", "allocation", "observed_at")
        if is_scd
        else ("vendor_id", "region_id", "database_id", "allocation")
    )

    # Multiple HA price rows collapse to one pre-v0.8.5 PK; keep lowest tier.
    _dedupe_database_price_for_pre_v085_pk(database_price_table_name, is_scd)

    if do_recreate_tables:
        with op.batch_alter_table(
            database_price_table_name,
            schema=None,
            copy_from=database_price_table,
            recreate="always",
        ) as batch_op:
            batch_op.drop_constraint(
                op.f(f"pk_{database_price_table_name}"), type_="primary"
            )
            batch_op.create_primary_key(
                op.f(f"pk_{database_price_table_name}"), list(database_price_pk)
            )
            batch_op.drop_column("ha_strategy")
            batch_op.drop_column("ha")
    else:
        op.drop_constraint(
            op.f(f"pk_{database_price_table_name}"),
            database_price_table_name,
            type_="primary",
        )
        op.create_primary_key(
            op.f(f"pk_{database_price_table_name}"),
            database_price_table_name,
            list(database_price_pk),
        )
        op.drop_column(database_price_table_name, "ha_strategy")
        op.drop_column(database_price_table_name, "ha")

    if is_postgresql:
        sa.Enum("STANDARD", name="databasesupportlevel").create(
            op.get_bind(), checkfirst=True
        )

    _downgrade_kept_column_comments = (
        ("family", "Database series or plan family slug."),
        ("server_id", "Optional reference to a related Server SKU."),
        ("vcpus", "Number of virtual CPUs (vCPU) of the database SKU."),
        ("memory_amount", "RAM amount (MiB) reported by the vendor."),
        (
            "engine_versions",
            "Supported major engine versions merged onto the SKU row.",
        ),
        ("storage_size", "Bundled storage size (GB), when included in the SKU."),
        (
            "scheduled_backups",
            "If scheduled/automated snapshot backups are supported.",
        ),
        ("continuous_backups", "Point-in-time recovery retention in days."),
        ("custom_config", "If custom configuration parameters are supported."),
        ("custom_extensions", "If custom extensions are supported."),
        ("sla", "Service level agreement as a percentage, e.g. 99.95."),
    )
    _downgrade_drop_new_columns = (
        "wire_protocol",
        "ha",
        "ha_strategy",
        "max_read_replicas",
        "storage_extra_min",
        "storage_extra_max",
        "disk_encryption",
        "connection_pool",
        "system_monitoring",
        "database_monitoring",
        "autotuning_apply",
        "security_features",
        "api_reference_object",
    )
    # Keys are pre-rename-back names from v0.8.5 schema; restored cols use final names.
    _downgrade_column_order = (
        "vendor_id",
        "database_id",
        "name",
        "api_reference",
        "display_name",
        "description",
        "server_id",
        "engine",
        "engine_versions",
        "family",
        "vcpus",
        "memory_amount",
        "storage_size",
        "ha_supported",
        "storage_extra_autosize",  # → storage_autoscaling
        "scheduled_backups",
        "continuous_backups",
        "auto_upgrade_versions",  # → engine_auto_upgrade
        "autotuning_advice",  # → autotuning
        "custom_config",
        "custom_extensions",
        "support_level",
        "sla",
        "status",
        "observed_at",
    )

    if do_recreate_tables:
        with op.batch_alter_table(
            database_table_name,
            schema=None,
            copy_from=database_table,
            recreate="always",
            partial_reordering=[_downgrade_column_order],
        ) as batch_op:
            for col in _downgrade_drop_new_columns:
                batch_op.drop_column(col)

            batch_op.alter_column(
                "storage_extra_autosize",
                new_column_name="storage_autoscaling",
                comment="If storage can be expanded beyond the bundled minimum.",
            )
            batch_op.alter_column(
                "auto_upgrade_versions",
                new_column_name="engine_auto_upgrade",
                comment="If automatic engine version upgrades are supported.",
            )
            batch_op.alter_column(
                "autotuning_advice",
                new_column_name="autotuning",
                comment="If vendor autotuning is available.",
            )
            batch_op.alter_column(
                "engine",
                nullable=False,
                comment="Managed database engine.",
            )
            for column, comment in _downgrade_kept_column_comments:
                batch_op.alter_column(column, comment=comment)

            batch_op.add_column(
                sa.Column(
                    "ha_supported",
                    sa.Boolean(),
                    nullable=True,
                    comment="If high availability is supported for the SKU.",
                ),
            )
            batch_op.add_column(
                sa.Column(
                    "support_level",
                    _enum("databasesupportlevel", ("STANDARD",)),
                    nullable=True,
                    comment="Vendor support tier for the SKU.",
                ),
            )
    else:
        for col in _downgrade_drop_new_columns:
            op.drop_column(database_table_name, col)

        op.alter_column(
            database_table_name,
            "storage_extra_autosize",
            new_column_name="storage_autoscaling",
            comment="If storage can be expanded beyond the bundled minimum.",
        )
        op.alter_column(
            database_table_name,
            "auto_upgrade_versions",
            new_column_name="engine_auto_upgrade",
            comment="If automatic engine version upgrades are supported.",
        )
        op.alter_column(
            database_table_name,
            "autotuning_advice",
            new_column_name="autotuning",
            comment="If vendor autotuning is available.",
        )
        op.alter_column(
            database_table_name,
            "engine",
            nullable=False,
            comment="Managed database engine.",
        )
        for column, comment in _downgrade_kept_column_comments:
            op.alter_column(database_table_name, column, comment=comment)

        op.add_column(
            database_table_name,
            sa.Column(
                "support_level",
                _enum("databasesupportlevel", ("STANDARD",)),
                nullable=True,
                comment="Vendor support tier for the SKU.",
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "ha_supported",
                sa.Boolean(),
                nullable=True,
                comment="If high availability is supported for the SKU.",
            ),
        )

    if is_postgresql:
        bind = op.get_bind()
        sa.Enum(name="databasewireprotocol").drop(bind, checkfirst=True)
        sa.Enum(name="databasehastrategy").drop(bind, checkfirst=True)
        sa.Enum(name="databasehalevel").drop(bind, checkfirst=True)
