"""The Spare Cores (SC) Crawler CLI functions.

Check `sc-crawler --help` for more details."""

import logging
from datetime import datetime, timedelta
from enum import Enum
from json import dumps, loads
from pathlib import Path
from typing import List

import typer
from cachier import set_default_params
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
from sqlmodel import Session, create_engine, select
from typing_extensions import Annotated

from . import vendors as vendors_module
from .insert import insert_items
from .logger import ProgressPanel, ScRichHandler, VendorProgressTracker, logger
from .lookup import compliance_frameworks, countries
from .table_fields import Status
from .tables import Vendor, tables
from .tables_scd import tables_scd
from .utils import HashLevels, get_row_by_pk, hash_database, table_name_to_model

supported_vendors = [
    vendor[1]
    for vendor in vars(vendors_module).items()
    if isinstance(vendor[1], Vendor)
]
Vendors = Enum("VENDORS", {k.vendor_id: k.vendor_id for k in supported_vendors})

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

table_names = [t.get_table_name() for t in tables]
Tables = Enum("TABLES", {k: k for k in table_names})


@cli.command()
def schema(
    dialect: Annotated[
        Engines,
        typer.Option(
            help="SQLAlchemy dialect to use for generating CREATE TABLE statements."
        ),
    ],
    scd: Annotated[
        bool, typer.Option(help="If SCD Type 2 tables should be also created.")
    ] = False,
):
    """
    Print the database schema in a SQL dialect.
    """
    url = engine_to_dialect[dialect.value]

    def metadata_dump(sql, *_args, **_kwargs):
        typer.echo(str(sql.compile(dialect=engine.dialect)) + ";")

    engine = create_engine(url, strategy="mock", executor=metadata_dump)
    for table in tables:
        table.__table__.create(engine)
    if scd:
        for table in tables_scd:
            table.__table__.create(engine)


@cli.command(name="hash")
def hash_command(
    connection_string: Annotated[
        str, typer.Option(help="Database URL with SQLAlchemy dialect.")
    ] = "sqlite:///sc-data-all.db",
):
    """Print the hash of the content of a database."""
    print(hash_database(connection_string))


@cli.command()
def copy(
    source: Annotated[
        str,
        typer.Option(
            help="Database URL (SQLAlchemy connection string) that is to be copied to `target`."
        ),
    ],
    target: Annotated[
        str,
        typer.Option(
            help="Database URL (SQLAlchemy connection string) that is to be populated with the content of `source`."
        ),
    ],
):
    """Copy the content of a database to a blank database."""

    source_engine = create_engine(source)
    target_engine = create_engine(target)

    for table in tables:
        table.__table__.create(target_engine, checkfirst=True)

    progress = Progress(
        TimeElapsedColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    )
    panel = Panel(progress, title="Copying tables", expand=False)

    with (
        Live(panel),
        Session(source_engine) as source_session,
        Session(target_engine) as target_session,
    ):
        for table in tables:
            rows = source_session.exec(statement=select(table))
            items = [row.model_dump() for row in rows]
            insert_items(table, items, session=target_session, progress=progress)
        target_session.commit()


@cli.command()
def sync(
    source: Annotated[
        str,
        typer.Option(
            help="Database URL (SQLAlchemy connection string) to sync to `update` based on `target`."
        ),
    ],
    target: Annotated[
        str,
        typer.Option(
            help="Database URL (SQLAlchemy connection string) to compare with `source`."
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(help="Stop after comparing the databases, do NOT insert rows."),
    ] = False,
    scd: Annotated[
        bool,
        typer.Option(help="Sync the changes to the SCD tables."),
    ] = False,
    log_changes_path: Annotated[
        Path,
        typer.Option(
            help="Optional file path to log the list of new/updated/deleted records."
        ),
    ] = None,
    log_changes_tables: Annotated[
        List[Tables],
        typer.Option(
            help="New/updated/deleted rows of a table to be logged. Can be specified multiple times."
        ),
    ] = table_names,
):
    """Sync a database to another one.

    Hashing both the `source` and the `target` databases, then
    comparing hashes and marking for syncing the following records:

    - new (rows with primary keys found in `source`, but not found in `target`)

    - update (rows with different values in `source` and in `target`).

    - inactive (rows with primary keys found in `target`, but not found in `source`).

    The records marked for syncing are written to the `target` database's
    standard or SCD tables. When updating the SCD tables, the hashing still
    happens on the standard tables/views, which are probably based on the
    most recent records of the SCD tables.
    """

    ps = Progress(
        TimeElapsedColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    )
    pt = Progress(
        TimeElapsedColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    )
    g = Table.grid(padding=1)
    g.add_row(
        Panel(ps, title="Hashing source database"),
        Panel(pt, title="Hashing target database"),
    )

    with Live(g):
        source_hash = hash_database(source, level=HashLevels.ROW, progress=ps)
        target_hash = hash_database(target, level=HashLevels.ROW, progress=pt)
    actions = {
        k: {table: [] for table in source_hash.keys()}
        for k in ["update", "new", "deleted"]
    }

    # enable logging
    channel = ScRichHandler()
    formatter = logging.Formatter("%(message)s")
    channel.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(channel)

    ps = Progress(
        TimeElapsedColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    )
    pt = Progress(
        TimeElapsedColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    )
    g = Table.grid(padding=1)
    g.add_row(
        Panel(ps, title="Comparing source database with target"),
        Panel(pt, title="Comparing target database with source"),
    )
    with Live(g):
        # compare new records with old
        engine = create_engine(source)
        with Session(engine) as session:
            tables_task_id = ps.add_task("Comparing tables", total=len(source_hash))
            for table_name, items in source_hash.items():
                table_task_id = ps.add_task(table_name, total=len(items))
                model = table_name_to_model(table_name)
                for pks_json, item in items.items():
                    action = None
                    try:
                        if item != target_hash[table_name][pks_json]:
                            action = "update"
                    except KeyError:
                        action = "new"
                    if action:
                        # get the new version of the record from the
                        # source database and store as JSON for future update
                        obj = get_row_by_pk(session, model, loads(pks_json))
                        actions[action][table_name].append(obj.model_dump())
                    ps.update(table_task_id, advance=1)
                ps.update(tables_task_id, advance=1)

        # compare old records with new
        engine = create_engine(target)
        with Session(engine) as session:
            tables_task_id = pt.add_task("Comparing tables", total=len(target_hash))
            for table_name, items in target_hash.items():
                table_task_id = pt.add_task(table_name, total=len(items))
                model = table_name_to_model(table_name)
                for key, _ in items.items():
                    if key not in source_hash[table_name]:
                        # check if the row was already set to INACTIVE
                        obj = get_row_by_pk(session, model, loads(key))
                        if obj.status != Status.INACTIVE:
                            obj.status = Status.INACTIVE
                            obj.observed_at = datetime.utcnow()
                            actions["deleted"][table_name].append(obj)
                    pt.update(table_task_id, advance=1)
                pt.update(tables_task_id, advance=1)

    stats = {ka: {ki: len(vi) for ki, vi in va.items()} for ka, va in actions.items()}
    table = Table(title="Sync results")
    table.add_column("Table", no_wrap=True)
    table.add_column("New rows", justify="right")
    table.add_column("Updated rows", justify="right")
    table.add_column("Deleted rows", justify="right")
    for table_name in source_hash.keys():
        table.add_row(
            table_name,
            str(stats["new"][table_name]),
            str(stats["update"][table_name]),
            str(stats["deleted"][table_name]),
        )
    console = Console()
    console.print(table)

    # log changes
    if log_changes_path:
        with open(log_changes_path, "w") as log_file:
            for table_name, _ in source_hash.items():
                if table_name in [t.value for t in log_changes_tables]:
                    if (
                        actions["new"][table_name]
                        or actions["update"][table_name]
                        or actions["deleted"][table_name]
                    ):
                        model = table_name_to_model(table_name)
                        pks = model.get_columns()["primary_keys"]
                        log_file.write(f"\n### {table_name}\n\n")
                        for action_types in ["new", "update", "deleted"]:
                            for item in actions[action_types][table_name]:
                                identifier = "/".join([item[key] for key in pks])
                                log_file.write(
                                    f"- {action_types.title()}: {identifier}\n"
                                )

    if not dry_run:
        progress = Progress(
            TimeElapsedColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
        )
        panel = Panel(progress, title="Updating target", expand=False)
        engine = create_engine(target)
        with Live(panel), Session(engine) as session:
            for table_name, _ in source_hash.items():
                model = table_name_to_model(table_name)
                if scd:
                    model = model.get_scd()
                items = (
                    actions["new"][table_name]
                    + actions["update"][table_name]
                    + actions["deleted"][table_name]
                )
                if len(items):
                    insert_items(model, items, session=session, progress=progress)
                    logger.info("Updated %d %s(s) rows" % (len(items), table_name))
            session.commit()


@cli.command()
def pull(
    connection_string: Annotated[
        str, typer.Option(help="Database URL with SQLAlchemy dialect.")
    ] = "sqlite:///sc-data-all.db",
    include_vendor: Annotated[
        List[Vendors],
        typer.Option(help="Enabled data sources. Can be specified multiple times."),
    ] = [v.vendor_id for v in supported_vendors],
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
        return dumps(x, default=lambda x: x.__json__(), allow_nan=False)

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
            vendor.vendor_id in [iv.value for iv in include_vendor]
            and vendor.vendor_id not in [ev.value for ev in exclude_vendor]
        )
    ]

    # filter reocrds
    records = [r for r in include_records if r not in exclude_records]

    engine = create_engine(connection_string, json_serializer=custom_serializer)
    for table in tables:
        table.__table__.create(engine, checkfirst=True)

    pbars = ProgressPanel()
    with Live(pbars.panels):
        # show CLI arguments in the Metadata panel
        pbars.metadata.append(Text("Data sources: ", style="bold"))
        pbars.metadata.append(Text(", ".join([x.vendor_id for x in vendors]) + " "))
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
                logger.info("Starting to collect data from vendor: " + vendor.vendor_id)
                vendor = session.merge(vendor)
                # register session to the Vendor so that dependen objects can auto-merge
                vendor.session = session
                # register progress bars so that helpers can update
                vendor.progress_tracker = VendorProgressTracker(
                    vendor=vendor, progress_panel=pbars
                )
                vendor.progress_tracker.start_vendor(total=len(records))
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
