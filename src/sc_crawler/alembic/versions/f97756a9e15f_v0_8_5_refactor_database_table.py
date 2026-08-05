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

    if do_recreate_tables:
        with op.batch_alter_table(
            database_table_name,
            schema=None,
            copy_from=database_table,
            recreate="always",
        ) as batch_op:
            for col in (
                "ha_supported",
                "storage_autoscaling",
                "engine_auto_upgrade",
                "autotuning",
                "support_level",
                "server_id",
                "engine",
                "engine_versions",
                "family",
                "vcpus",
                "memory_amount",
                "storage_size",
                "scheduled_backups",
                "continuous_backups",
                "custom_config",
                "custom_extensions",
                "sla",
            ):
                batch_op.drop_column(col)

            batch_op.add_column(
                sa.Column(
                    "api_reference_object",
                    json_type(),
                    nullable=True,
                    comment="How this resource is referenced in the vendor API calls, including the parameter name(s).",
                ),
                insert_after="api_reference",
            )

            columns_in_order = [
                (
                    "family",
                    sqlmodel.sql.sqltypes.AutoString(),
                    True,
                    None,
                    "Hardware family or class classification.",
                ),
                (
                    "server_id",
                    sqlmodel.sql.sqltypes.AutoString(),
                    True,
                    None,
                    "Reference to the underlying cloud server's identifier.",
                ),
                (
                    "vcpus",
                    sa.Integer(),
                    True,
                    None,
                    "Number of virtual CPU cores allocated to the database "
                    "server instance.",
                ),
                (
                    "memory_amount",
                    sa.Integer(),
                    True,
                    None,
                    "Amount of RAM (MiB) provisioned for the instance.",
                ),
                (
                    "engine",
                    _enum("databaseengine", ("POSTGRESQL",)),
                    True,
                    None,
                    "Managed database engine running on the instance.",
                ),
                (
                    "wire_protocol",
                    sa.Enum("POSTGRESQL", name="databasewireprotocol"),
                    True,
                    None,
                    "Network protocol used for client connections.",
                ),
                (
                    "engine_versions",
                    json_type(),
                    False,
                    None,
                    "Major database engine versions supported.",
                ),
                (
                    "auto_upgrade_versions",
                    sa.Boolean(),
                    True,
                    None,
                    "Auto-upgrade between minor database engine versions.",
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
                    "custom_config",
                    sa.Boolean(),
                    True,
                    None,
                    "Whether database engine parameters/flags can be customized.",
                ),
                (
                    "custom_extensions",
                    sa.Boolean(),
                    True,
                    None,
                    "Support for custom database engine extensions/plugins.",
                ),
                (
                    "storage_size",
                    sa.Integer(),
                    True,
                    None,
                    "Bundled storage capacity included in the database (GB).",
                ),
                (
                    "storage_extra_min",
                    sa.Integer(),
                    True,
                    None,
                    "Minimum custom storage size (in GB) that can be attached "
                    "to the instance.",
                ),
                (
                    "storage_extra_max",
                    sa.Integer(),
                    True,
                    None,
                    "Maximum storage limit (in GB) supported by the instance "
                    "or storage tier.",
                ),
                (
                    "storage_extra_autosize",
                    sa.Boolean(),
                    True,
                    None,
                    "Whether storage capacity can automatically expand as "
                    "disk usage grows.",
                ),
                (
                    "disk_encryption",
                    sa.Boolean(),
                    True,
                    None,
                    "Indicates whether underlying storage drives are encrypted at rest.",
                ),
                (
                    "scheduled_backups",
                    sa.Boolean(),
                    True,
                    None,
                    "Support for automated snapshot schedules and backup "
                    "retention management.",
                ),
                (
                    "continuous_backups",
                    sa.Integer(),
                    True,
                    None,
                    "Maximum point-in-time recovery (PITR) log retention window "
                    "expressed in days (0 if unsupported).",
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
                    "autotuning_advice",
                    sa.Boolean(),
                    True,
                    None,
                    "Analyzes workload and generates actionable performance tuning advice.",
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
                    "sla",
                    sa.Float(),
                    True,
                    None,
                    "Service level agreement as a percentage, e.g. 99.95.",
                ),
                (
                    "security_features",
                    json_type(),
                    False,
                    "[]",
                    "Security capabilities supported by DBaaS providers.",
                ),
            ]
            after = "description"
            for name, coltype, nullable, server_default, comment in columns_in_order:
                kwargs = {
                    "nullable": nullable,
                    "comment": comment,
                }
                if server_default is not None:
                    kwargs["server_default"] = server_default
                batch_op.add_column(
                    sa.Column(name, coltype, **kwargs),
                    insert_after=after,
                )
                after = name
    else:
        op.drop_column(database_table_name, "ha_supported")
        op.drop_column(database_table_name, "storage_autoscaling")
        op.drop_column(database_table_name, "engine_auto_upgrade")
        op.drop_column(database_table_name, "autotuning")
        op.drop_column(database_table_name, "support_level")

        if is_postgresql:
            bind = op.get_bind()
            sa.Enum("POSTGRESQL", name="databasewireprotocol").create(
                bind, checkfirst=True
            )

        op.alter_column(database_table_name, "engine", nullable=True)
        op.add_column(
            database_table_name,
            sa.Column(
                "api_reference_object",
                json_type(),
                nullable=True,
                comment="How this resource is referenced in the vendor API calls, including the parameter name(s).",
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "wire_protocol",
                sa.Enum("POSTGRESQL", name="databasewireprotocol"),
                nullable=True,
                comment="Network protocol used for client connections.",
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "auto_upgrade_versions",
                sa.Boolean(),
                nullable=True,
                comment="Auto-upgrade between minor database engine versions.",
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "ha",
                json_type(),
                nullable=False,
                server_default='["none"]',
                comment="Ordered HA levels supported, highest tier first.",
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "ha_strategy",
                json_type(),
                nullable=False,
                server_default='["none"]',
                comment="Ordered HA strategies supported, highest tier first.",
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "max_read_replicas",
                sa.Integer(),
                nullable=True,
                comment=(
                    "Maximum number of read-only replica nodes supported "
                    "to scale read workloads."
                ),
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "storage_extra_min",
                sa.Integer(),
                nullable=True,
                comment=(
                    "Minimum custom storage size (in GB) that can be attached "
                    "to the instance."
                ),
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "storage_extra_max",
                sa.Integer(),
                nullable=True,
                comment=(
                    "Maximum storage limit (in GB) supported by the instance "
                    "or storage tier."
                ),
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "storage_extra_autosize",
                sa.Boolean(),
                nullable=True,
                comment=(
                    "Whether storage capacity can automatically expand as "
                    "disk usage grows."
                ),
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "disk_encryption",
                sa.Boolean(),
                nullable=True,
                comment=(
                    "Indicates whether underlying storage drives are encrypted at rest."
                ),
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "connection_pool",
                sa.Boolean(),
                nullable=True,
                comment="Managed connection proxy support.",
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "system_monitoring",
                sa.Boolean(),
                nullable=True,
                comment=(
                    "Availability of host-level CPU, RAM, and disk metrics dashboards."
                ),
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "database_monitoring",
                sa.Boolean(),
                nullable=True,
                comment=(
                    "Database engine performance insights "
                    "(slow queries, locks, execution plans)."
                ),
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "autotuning_advice",
                sa.Boolean(),
                nullable=True,
                comment=(
                    "Analyzes workload and generates actionable performance "
                    "tuning advice."
                ),
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "autotuning_apply",
                sa.Boolean(),
                nullable=True,
                comment=(
                    "System automatically executes performance fixes "
                    "(e.g., index creation, parameter tuning) without "
                    "operator intervention."
                ),
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "security_features",
                json_type(),
                nullable=False,
                server_default="[]",
                comment="Security capabilities supported by DBaaS providers.",
            ),
        )
        for column, comment in (
            ("family", "Hardware family or class classification."),
            ("server_id", "Reference to the underlying cloud server's identifier."),
            (
                "vcpus",
                "Number of virtual CPU cores allocated to the database server instance.",
            ),
            ("memory_amount", "Amount of RAM (MiB) provisioned for the instance."),
            ("engine", "Managed database engine running on the instance."),
            ("engine_versions", "Major database engine versions supported."),
            (
                "storage_size",
                "Bundled storage capacity included in the database (GB).",
            ),
            (
                "scheduled_backups",
                "Support for automated snapshot schedules and backup retention management.",
            ),
            (
                "continuous_backups",
                "Maximum point-in-time recovery (PITR) log retention window expressed in days (0 if unsupported).",
            ),
            (
                "custom_config",
                "Whether database engine parameters/flags can be customized.",
            ),
            (
                "custom_extensions",
                "Support for custom database engine extensions/plugins.",
            ),
        ):
            op.alter_column(database_table_name, column, comment=comment)

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
    json_type = sa.dialects.postgresql.JSONB if is_postgresql else sa.JSON
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

    if do_recreate_tables:
        with op.batch_alter_table(
            database_table_name,
            schema=None,
            copy_from=database_table,
            recreate="always",
        ) as batch_op:
            for col in (
                "wire_protocol",
                "auto_upgrade_versions",
                "ha",
                "ha_strategy",
                "max_read_replicas",
                "storage_extra_min",
                "storage_extra_max",
                "storage_extra_autosize",
                "disk_encryption",
                "connection_pool",
                "system_monitoring",
                "database_monitoring",
                "autotuning_advice",
                "autotuning_apply",
                "security_features",
                "api_reference_object",
                "family",
                "server_id",
                "vcpus",
                "memory_amount",
                "engine",
                "engine_versions",
                "custom_config",
                "custom_extensions",
                "storage_size",
                "scheduled_backups",
                "continuous_backups",
                "sla",
            ):
                batch_op.drop_column(col)

            columns_in_order = [
                (
                    "server_id",
                    sqlmodel.sql.sqltypes.AutoString(),
                    True,
                    "Optional reference to a related Server SKU.",
                ),
                (
                    "engine",
                    _enum("databaseengine", ("POSTGRESQL",)),
                    False,
                    "Managed database engine.",
                ),
                (
                    "engine_versions",
                    json_type(),
                    False,
                    "Supported major engine versions merged onto the SKU row.",
                ),
                (
                    "family",
                    sqlmodel.sql.sqltypes.AutoString(),
                    True,
                    "Database series or plan family slug.",
                ),
                (
                    "vcpus",
                    sa.Integer(),
                    True,
                    "Number of virtual CPUs (vCPU) of the database SKU.",
                ),
                (
                    "memory_amount",
                    sa.Integer(),
                    True,
                    "RAM amount (MiB) reported by the vendor.",
                ),
                (
                    "storage_size",
                    sa.Integer(),
                    True,
                    "Bundled storage size (GB), when included in the SKU.",
                ),
                (
                    "ha_supported",
                    sa.Boolean(),
                    True,
                    "If high availability is supported for the SKU.",
                ),
                (
                    "storage_autoscaling",
                    sa.Boolean(),
                    True,
                    "If storage can be expanded beyond the bundled minimum.",
                ),
                (
                    "scheduled_backups",
                    sa.Boolean(),
                    True,
                    "If scheduled/automated snapshot backups are supported.",
                ),
                (
                    "continuous_backups",
                    sa.Integer(),
                    True,
                    "Point-in-time recovery retention in days.",
                ),
                (
                    "engine_auto_upgrade",
                    sa.Boolean(),
                    True,
                    "If automatic engine version upgrades are supported.",
                ),
                (
                    "autotuning",
                    sa.Boolean(),
                    True,
                    "If vendor autotuning is available.",
                ),
                (
                    "custom_config",
                    sa.Boolean(),
                    True,
                    "If custom configuration parameters are supported.",
                ),
                (
                    "custom_extensions",
                    sa.Boolean(),
                    True,
                    "If custom extensions are supported.",
                ),
                (
                    "support_level",
                    _enum("databasesupportlevel", ("STANDARD",)),
                    True,
                    "Vendor support tier for the SKU.",
                ),
                (
                    "sla",
                    sa.Float(),
                    True,
                    "Service level agreement as a percentage, e.g. 99.95.",
                ),
            ]
            after = "description"
            for name, coltype, nullable, comment in columns_in_order:
                batch_op.add_column(
                    sa.Column(name, coltype, nullable=nullable, comment=comment),
                    insert_after=after,
                )
                after = name
    else:
        op.drop_column(database_table_name, "wire_protocol")
        op.drop_column(database_table_name, "auto_upgrade_versions")
        op.drop_column(database_table_name, "ha")
        op.drop_column(database_table_name, "ha_strategy")
        op.drop_column(database_table_name, "max_read_replicas")
        op.drop_column(database_table_name, "storage_extra_min")
        op.drop_column(database_table_name, "storage_extra_max")
        op.drop_column(database_table_name, "storage_extra_autosize")
        op.drop_column(database_table_name, "disk_encryption")
        op.drop_column(database_table_name, "connection_pool")
        op.drop_column(database_table_name, "system_monitoring")
        op.drop_column(database_table_name, "database_monitoring")
        op.drop_column(database_table_name, "autotuning_advice")
        op.drop_column(database_table_name, "autotuning_apply")
        op.drop_column(database_table_name, "security_features")
        op.drop_column(database_table_name, "api_reference_object")

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
        op.add_column(
            database_table_name,
            sa.Column(
                "storage_autoscaling",
                sa.Boolean(),
                nullable=True,
                comment="If storage can be expanded beyond the bundled minimum.",
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "engine_auto_upgrade",
                sa.Boolean(),
                nullable=True,
                comment="If automatic engine version upgrades are supported.",
            ),
        )
        op.add_column(
            database_table_name,
            sa.Column(
                "autotuning",
                sa.Boolean(),
                nullable=True,
                comment="If vendor autotuning is available.",
            ),
        )
        for column, comment in (
            ("family", "Database series or plan family slug."),
            ("server_id", "Optional reference to a related Server SKU."),
            ("vcpus", "Number of virtual CPUs (vCPU) of the database SKU."),
            ("memory_amount", "RAM amount (MiB) reported by the vendor."),
            ("engine", "Managed database engine."),
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
            ("support_level", "Vendor support tier for the SKU."),
        ):
            op.alter_column(database_table_name, column, comment=comment)

    if is_postgresql:
        bind = op.get_bind()
        sa.Enum(name="databasewireprotocol").drop(bind, checkfirst=True)
        sa.Enum(name="databasehastrategy").drop(bind, checkfirst=True)
        sa.Enum(name="databasehalevel").drop(bind, checkfirst=True)
