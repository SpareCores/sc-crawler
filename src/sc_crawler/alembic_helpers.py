from os.path import dirname, join
from typing import Optional

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection

pkg_folder = dirname(__file__)


def alembic_cfg(
    connection, scd: Optional[bool] = None, force_logging: bool = True
) -> Config:
    """Loads the Alembic config and sets some dynamic attributes."""
    alembic_cfg = Config(join(pkg_folder, "alembic.ini"))
    alembic_cfg.attributes["force_logging"] = force_logging
    if scd is not None:
        alembic_cfg.attributes["scd"] = scd
    alembic_cfg.attributes["connection"] = connection
    alembic_cfg.set_main_option("script_location", join(pkg_folder, "alembic"))
    return alembic_cfg


def get_revision(
    connection: Connection, version_table: str = "zzz_alembic_version"
) -> str:
    """Get current revision of alembic in a database connection.

    Args:
        connection: SQLAlchemy connection to look up revision in `version_table`
        version_table: name of the table storing revision"""
    return MigrationContext.configure(
        connection, opts={"version_table": version_table}
    ).get_current_revision()
