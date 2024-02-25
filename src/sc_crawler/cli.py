import logging
from datetime import timedelta
from enum import Enum
from json import dumps
from typing import List

import typer
from cachier import set_default_params
from sqlmodel import Session, SQLModel, create_engine
from typing_extensions import Annotated

from . import vendors as vendors_module
from .logger import ScRichHandler, logger
from .lookup import compliance_frameworks, countries
from .schemas import Vendor
from .utils import hash_database

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

supported_tables = [m[10:] for m in dir(Vendor) if m.startswith("inventory_")]
Tables = Enum("TABLES", {k: k for k in supported_tables})


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
):
    """Print the hash of the content of a database."""
    print(hash_database(connection_string))


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
    update_table: Annotated[
        List[Tables],
        typer.Option(help="Tables to be updated. Can be specified multiple times."),
    ] = supported_tables,
    log_level: Annotated[
        LogLevels, typer.Option(help="Log level threshold.")
    ] = LogLevels.INFO.value,  # TODO drop .value after updating Enum to StrEnum in Python3.11
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
    channel = ScRichHandler()
    formatter = logging.Formatter("%(message)s")
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
        # add/merge static objects to database
        for compliance_framework in compliance_frameworks.values():
            session.merge(compliance_framework)
        for country in countries.values():
            session.merge(country)
        # get data for each vendor and then add/merge to database
        for vendor in vendors:
            logger.info("Starting to collect data from vendor: " + vendor.id)
            vendor = session.merge(vendor)
            if Tables.compliance_frameworks in update_table:
                vendor.inventory_compliance_frameworks()
            if Tables.datacenters in update_table:
                vendor.inventory_datacenters()
            if Tables.zones in update_table:
                vendor.inventory_zones()
            if Tables.servers in update_table:
                vendor.inventory_servers()
            if Tables.server_prices in update_table:
                vendor.inventory_server_prices()
            if Tables.server_prices_spot in update_table:
                vendor.inventory_server_prices_spot()
            if Tables.storage_prices in update_table:
                vendor.inventory_storage_prices()
            if Tables.traffic_prices in update_table:
                vendor.inventory_traffic_prices()
            if Tables.ipv4_prices in update_table:
                vendor.inventory_ipv4_prices()
            session.merge(vendor)
            session.commit()
                vendor.session = session


if __name__ == "__main__":
    pull()
