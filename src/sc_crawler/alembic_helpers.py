from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection


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
