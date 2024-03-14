"""The Spare Cores (SC) Crawler CLI tool.

Provides the `sc-crawler` command and the below subcommands:

- [schema][sc_crawler.cli.schema]
- [pull][sc_crawler.cli.pull]
- [hash][sc_crawler.cli.hash_command]
"""

import logging
from datetime import datetime, timedelta
from enum import Enum
from json import dumps
from typing import List

import typer
from cachier import set_default_params
from rich.live import Live
from rich.text import Text
from sqlmodel import Session, SQLModel, create_engine
from typing_extensions import Annotated

from . import vendors as vendors_module
from .logger import ProgressPanel, ScRichHandler, VendorProgressTracker, logger
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

supported_records = [r[10:] for r in dir(Vendor) if r.startswith("inventory_")]
Records = Enum("RECORDS", {k: k for k in supported_records})


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
        typer.Option(help="Enabled data sources. Can be specified multiple times."),
    ] = [v.id for v in supported_vendors],
    exclude_vendor: Annotated[
        List[Vendors],
        typer.Option(help="Disabled data sources. Can be specified multiple times."),
    ] = [],
    include_records: Annotated[
        List[Records],
        typer.Option(
            help="Database records to be updated. Can be specified multiple times."
        ),
    ] = supported_records,
    exclude_records: Annotated[
        List[Records],
        typer.Option(
            help="Database records NOT to be updated. Can be specified multiple times."
        ),
    ] = [],
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
    vendors = [
        vendor
        for vendor in supported_vendors
        if (
            vendor.id in [iv.value for iv in include_vendor]
            and vendor.id not in [ev.value for ev in exclude_vendor]
        )
    ]

    # filter reocrds
    records = [r for r in include_records if r not in exclude_records]

    engine = create_engine(connection_string, json_serializer=custom_serializer)
    SQLModel.metadata.create_all(engine)

    pbars = ProgressPanel()
    with Live(pbars.panels):
        # show CLI arguments in the Metadata panel
        pbars.metadata.append(Text("Data sources: ", style="bold"))
        pbars.metadata.append(Text(", ".join([x.id for x in vendors]) + " "))
        pbars.metadata.append(Text("Updating records: ", style="bold"))
        pbars.metadata.append(Text(", ".join([x.value for x in records]) + "\n"))
        pbars.metadata.append(Text("Connection type: ", style="bold"))
        pbars.metadata.append(Text(connection_string.split(":")[0]))
        pbars.metadata.append(Text(" Cache: ", style="bold"))
        if cache:
            pbars.metadata.append(Text("Enabled (" + str(cache_ttl) + "m)"))
        else:
            pbars.metadata.append(Text("Disabled"))
        pbars.metadata.append(Text(" Time: ", style="bold"))
        pbars.metadata.append(Text(str(datetime.now())))

        with Session(engine) as session:
            # add/merge static objects to database
            for compliance_framework in compliance_frameworks.values():
                session.merge(compliance_framework)
            logger.info("%d Compliance Frameworks synced." % len(compliance_frameworks))
            for country in countries.values():
                session.merge(country)
            logger.info("%d Countries synced." % len(countries))
            # get data for each vendor and then add/merge to database
            # TODO each vendor should open its own session and run in parallel
            for vendor in vendors:
                logger.info("Starting to collect data from vendor: " + vendor.id)
                vendor = session.merge(vendor)
                # register session to the Vendor so that dependen objects can auto-merge
                vendor.session = session
                # register progress bars so that helpers can update
                vendor.progress_tracker = VendorProgressTracker(
                    vendor=vendor, progress_panel=pbars
                )
                vendor.progress_tracker.start_vendor(n=len(records))
                if Records.compliance_frameworks in records:
                    vendor.inventory_compliance_frameworks()
                if Records.datacenters in records:
                    vendor.inventory_datacenters()
                if Records.zones in records:
                    vendor.inventory_zones()
                if Records.servers in records:
                    vendor.inventory_servers()
                if Records.server_prices in records:
                    vendor.inventory_server_prices()
                if Records.server_prices_spot in records:
                    vendor.inventory_server_prices_spot()
                if Records.storages in records:
                    vendor.inventory_storages()
                if Records.storage_prices in records:
                    vendor.inventory_storage_prices()
                if Records.traffic_prices in records:
                    vendor.inventory_traffic_prices()
                if Records.ipv4_prices in records:
                    vendor.inventory_ipv4_prices()
                # reset current step name
                vendor.progress_tracker.update_vendor(step="✔")
                session.merge(vendor)
                session.commit()

        pbars.metadata.append(Text(" - " + str(datetime.now())))


if __name__ == "__main__":
    pull()
