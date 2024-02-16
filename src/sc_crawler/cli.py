import logging
from datetime import timedelta
from enum import Enum
from hashlib import sha1
from json import dumps
from typing import List

import typer
from cachier import set_default_params
from sqlmodel import Session, SQLModel, create_engine
from typing_extensions import Annotated

from . import vendors as vendors_module
from .logger import logger
from .schemas import Vendor, tables

supported_vendors = [
    vendor[1]
    for vendor in vars(vendors_module).items()
    if isinstance(vendor[1], Vendor)
]
Vendors = Enum("VENDORS", {k.id: k.id for k in supported_vendors})

cli = typer.Typer()

engine_to_dialect = {
    "postgresql": "postgresql+psycopg2://",
    "mysql": "mysql+pymysql://",
    "sqlite": "sqlite://",
    "oracle": "oracle+cx_oracle://",
    "sqlserver": "mssql+pyodbc://",
}
Engines = Enum("ENGINES", {k: k for k in engine_to_dialect.keys()})

# TODO use logging.getLevelNamesMapping() from Python 3.11
log_levels = list(logging._nameToLevel.keys())
LogLevels = Enum("LOGLEVELS", {k: k for k in log_levels})


class HashLevels(Enum):
    DATABASE = "database"
    TABLE = "table"
    ROW = "row"


@cli.command()
def schema(dialect: Engines):
    """
    Print the database schema in a SQL dialect.
    """
    url = engine_to_dialect[dialect.value]

    def metadata_dump(sql, *_args, **_kwargs):
        typer.echo(str(sql.compile(dialect=engine.dialect)) + ";")

    engine = create_engine(url, strategy="mock", executor=metadata_dump)
    SQLModel.metadata.create_all(engine)


@cli.command(name="hash")
def hash_command(
    connection_string: Annotated[
        str, typer.Option(help="Database URL with SQLAlchemy dialect.")
    ] = "sqlite:///sc_crawler.db",
    level: Annotated[
        HashLevels,
        typer.Option(
            help="Return hashes for the whole database, per table or for each row."
        ),
    ] = "database",
):
    engine = create_engine(connection_string)

    with Session(engine) as session:
        table_hashes = {table.get_table_name(): table.hash(session) for table in tables}

    if level == HashLevels.TABLE:
        table_hashes = {
            k: sha1(dumps(v, sort_keys=True).encode()).hexdigest()
            for k, v in table_hashes.items()
        }
        print(dumps(table_hashes, sort_keys=True))
        raise typer.Exit()

    json_dump = dumps(table_hashes, sort_keys=True)
    if level == HashLevels.ROW:
        print(json_dump)

    if level == HashLevels.DATABASE:
        print(sha1(json_dump.encode()).hexdigest())


@cli.command()
def pull(
    connection_string: Annotated[
        str, typer.Option(help="Database URL with SQLAlchemy dialect.")
    ] = "sqlite:///sc_crawler.db",
    include_vendor: Annotated[
        List[Vendors],
        typer.Option(
            help="Filter for specific vendor. Can be specified multiple times."
        ),
    ] = [],
    exclude_vendor: Annotated[
        List[Vendors],
        typer.Option(help="Exclude specific vendor. Can be specified multiple times."),
    ] = [],
    log_level: Annotated[LogLevels, typer.Option(help="Log level threshold.")] = "INFO",
    cache: Annotated[
        bool,
        typer.Option(help="Enable or disable caching of all vendor API calls on disk."),
    ] = False,
    cache_ttl: Annotated[
        int,
        typer.Option(help="Cache Time-to-live in minutes. Defaults to one day."),
    ] = 60 * 24,  # 1 day
):
    """
    Pull data from available vendor APIs and store in a database.

    Vendor API calls are optionally cached as Pickle objects in `~/.cachier`.
    """

    def custom_serializer(x):
        """Use JSON serializer defined in custom objects."""
        return dumps(x, default=lambda x: x.__json__())

    # enable caching
    if cache:
        set_default_params(
            caching_enabled=True,
            stale_after=timedelta(minutes=cache_ttl),
        )

    # enable logging
    channel = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    channel.setFormatter(formatter)
    logger.setLevel(log_level.value)
    logger.addHandler(channel)

    # filter vendors
    vendors = supported_vendors
    vendors = [
        vendor
        for vendor in vendors
        if (
            vendor.id in [vendor.value for vendor in include_vendor]
            and vendor.id not in [vendor.value for vendor in exclude_vendor]
        )
    ]

    engine = create_engine(connection_string, json_serializer=custom_serializer)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for vendor in vendors:
            logger.info("Starting to collect data from vendor: " + vendor.id)
            vendor.get_all()
            session.add(vendor)
            session.commit()


if __name__ == "__main__":
    pull()
