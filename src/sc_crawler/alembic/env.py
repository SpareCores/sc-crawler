import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

scd = config.attributes.get("scd", False)
logging_forced = config.attributes.get("force_logging", False)
logging_inited = bool(logging.getLogger("sc_crawler").handlers)

# Set up logging if was not done already
if not logging_inited or logging_forced:
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)

# add your model's MetaData object here
from sc_crawler.tables import tables  # noqa: F401 E402
from sc_crawler.tables_scd import tables_scd  # noqa: F401 E402

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """

    # use DB connection if available
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        url = connectable.engine.url
    else:
        url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context -
    if not already available.
    """

    # use DB connection if available
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        context.configure(
            connection=connectable,
            target_metadata=target_metadata,
            version_table="zzz_alembic_version",
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                version_table="zzz_alembic_version",
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
