"""The Spare Cores (SC) Crawler CLI functions.

Check `sc-crawler --help` for more details."""

import logging
from contextlib import suppress
from datetime import datetime, timedelta
from enum import Enum
from json import dump as json_dump
from json import dumps, loads
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

import typer
from alembic import command
from cachier import set_global_params
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
from sqlalchemy import text
from sqlalchemy.engine.reflection import Inspector
from sqlmodel import Session, create_engine, select
from typing_extensions import Annotated

from . import vendors as vendors_module
from .alembic_helpers import alembic_cfg, get_revision
from .insert import insert_items
from .logger import ProgressPanel, ScRichHandler, VendorProgressTracker, logger
from .lookup import benchmarks, compliance_frameworks, countries
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


alembic_app = typer.Typer()
cli.add_typer(
    alembic_app, name="schemas", help="Database migration utilities using Alembic."
)

options = SimpleNamespace(
    connection_string=Annotated[
        str, typer.Option(help="Database URL with SQLAlchemy dialect.")
    ],
    revision=Annotated[
        str,
        typer.Option(
            help="Target revision passed to Alembic. Use 'heads' to get to the most recent version."
        ),
    ],
    scd=Annotated[
        bool,
        typer.Option(help="Migrate the SCD tables instead of the standard tables."),
    ],
    sql=Annotated[
        bool,
        typer.Option(help="Dry-run, printing the SQL commands instead of running."),
    ],
)


@alembic_app.command()
def create(
    connection_string: Annotated[
        Optional[str], typer.Option(help="Database URL with SQLAlchemy dialect.")
    ] = None,
    dialect: Annotated[
        Optional[Engines],
        typer.Option(
            help="SQLAlchemy dialect to use for generating CREATE TABLE statements."
        ),
    ] = None,
    scd: Annotated[
        bool, typer.Option(help="If SCD Type 2 tables should be also created.")
    ] = False,
):
    """
    Print the database schema in a SQL dialect.

    Either `connection_string` or `dialect` is to be provided to decide
    what SQL dialect to use to generate the CREATE TABLE (and related)
    SQL statements.
    """
    if connection_string is None and dialect is None:
        print("Either connection_string or dialect parameters needs to be provided!")
        raise typer.Exit(code=1)
    if dialect:
        url = engine_to_dialect[dialect.value]
    else:
        url = connection_string

    def metadata_dump(sql, *_args, **_kwargs):
        typer.echo(str(sql.compile(dialect=engine.dialect)) + ";")

    engine = create_engine(url, strategy="mock", executor=metadata_dump)
    for table in tables:
        table.__table__.create(engine)
    if scd:
        for table in tables_scd:
            table.__table__.create(engine)


@alembic_app.command()
def current(
    connection_string: options.connection_string = "sqlite:///sc-data-all.db",
    scd: options.scd = False,
):
    """
    Show current database revision.
    """
    engine = create_engine(connection_string)
    with engine.begin() as connection:
        command.current(alembic_cfg(connection, scd))


@alembic_app.command()
def upgrade(
    connection_string: options.connection_string = "sqlite:///sc-data-all.db",
    revision: options.revision = "heads",
    scd: options.scd = False,
    sql: options.sql = False,
):
    """
    Upgrade the database schema to a given (default: most recent) revision.
    """
    engine = create_engine(connection_string)
    with engine.begin() as connection:
        command.upgrade(alembic_cfg(connection, scd), revision, sql)


@alembic_app.command()
def downgrade(
    connection_string: options.connection_string = "sqlite:///sc-data-all.db",
    revision: options.revision = "-1",
    scd: options.scd = False,
    sql: options.sql = False,
):
    """
    Downgrade the database schema to a given (default: previous) revision.
    """
    engine = create_engine(connection_string)
    with engine.begin() as connection:
        command.downgrade(alembic_cfg(connection, scd), revision, sql)


@alembic_app.command()
def stamp(
    connection_string: options.connection_string = "sqlite:///sc-data-all.db",
    revision: options.revision = "heads",
    scd: options.scd = False,
    sql: options.sql = False,
):
    """
    Set the migration revision mark in the database to a specified revision. Set to "heads" if the database schema is up-to-date.
    """
    engine = create_engine(connection_string)
    with engine.begin() as connection:
        command.stamp(alembic_cfg(connection, scd), revision, sql)


@alembic_app.command()
def autogenerate(
    connection_string: options.connection_string = "sqlite:///sc-data-all.db",
    message: Annotated[
        str,
        typer.Option(help="Revision message, e.g. SC Crawler version number."),
    ] = "empty message",
):
    """
    Autogenerate a migrations script based on the current state of a database.
    """
    engine = create_engine(connection_string)
    with engine.begin() as connection:
        command.revision(
            alembic_cfg(connection=connection), autogenerate=True, message=message
        )


@cli.command(name="hash")
def hash_command(
    connection_string: options.connection_string = "sqlite:///sc-data-all.db",
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
    """Copy the standard SC Crawler tables of a database into a blank database."""

    source_engine = create_engine(source, pool_pre_ping=True)
    target_engine = create_engine(target, pool_pre_ping=True)

    for table in tables:
        table.__table__.create(target_engine)

    progress = Progress(
        TimeElapsedColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    )
    panel = Panel(progress, title="Copying tables", expand=False)

    with Live(panel):
        for table in tables:
            with Session(source_engine) as source_session:
                rows = source_session.exec(statement=select(table))
                items = [row.model_dump() for row in rows]
            with Session(target_engine) as target_session:
                insert_items(table, items, session=target_session, progress=progress)
                target_session.commit()
    with target_engine.begin() as connection:
        command.stamp(alembic_cfg(connection), "heads")


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
    sync_tables: Annotated[
        List[Tables],
        typer.Option(help="Tables to be synced. Can be specified multiple times."),
    ] = table_names,
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

    source_engine = create_engine(source, pool_pre_ping=True)
    target_engine = create_engine(target, pool_pre_ping=True)

    # compare source and target database revisions, halt if not matching
    with source_engine.connect() as connection:
        current_rev = get_revision(connection)
    with target_engine.begin() as connection:
        target_rev = get_revision(connection)
    if current_rev != target_rev:
        print(
            "Database revisions do NOT match, so not risking the sync. "
            "Upgrade the database(s) before trying again!"
        )
        raise typer.Exit(code=1)

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

    exclude_tables = [
        t for t in tables if t.get_table_name() not in [t.value for t in sync_tables]
    ]
    with Live(g):
        source_hash = hash_database(
            source, level=HashLevels.ROW, progress=ps, exclude_tables=exclude_tables
        )
        target_hash = hash_database(
            target, level=HashLevels.ROW, progress=pt, exclude_tables=exclude_tables
        )
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
        with Session(source_engine) as session:
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
        with Session(target_engine) as session:
            tables_task_id = pt.add_task("Comparing tables", total=len(target_hash))
            for table_name, items in target_hash.items():
                table_task_id = pt.add_task(table_name, total=len(items))
                model = table_name_to_model(table_name)
                for key, _ in items.items():
                    if key not in source_hash[table_name]:
                        # check if the row was already set to INACTIVE
                        obj = get_row_by_pk(session, model, loads(key)).model_dump()
                        if obj["status"] != Status.INACTIVE:
                            obj["status"] = Status.INACTIVE
                            obj["observed_at"] = datetime.utcnow()
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
        with Live(panel), Session(target_engine) as session:
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
def dump(
    connection_string: Annotated[
        str,
        typer.Option(
            help="Database URL (SQLAlchemy connection string) to export from."
        ),
    ],
    output_directory: Annotated[
        Path,
        typer.Option(help="Directory path where JSON files will be written."),
    ] = Path("."),
    dump_tables: Annotated[
        Optional[List[str]],
        typer.Option(
            help="Tables to be dumped. Can be specified multiple times. Defaults to all tables."
        ),
    ] = None,
    ignored: Annotated[
        List[str],
        typer.Option(
            help="Column names to exclude from JSON output. Can be specified multiple times."
        ),
    ] = ["observed_at"],
):
    """
    Export database records to JSON files organized by primary keys.

    Each record is written as a pretty-printed JSON file in a folder
    hierarchy based on the primary key values. For example, a server
    record with vendor_id='aws' and server_id='t3.small' would be
    written to: `output_directory/server/aws/t3.small.json`
    """
    channel = ScRichHandler()
    formatter = logging.Formatter("%(message)s")
    channel.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.addHandler(channel)

    engine = create_engine(connection_string, pool_pre_ping=True)
    inspector = Inspector.from_engine(engine)
    available_tables = inspector.get_table_names()
    if dump_tables is None:
        tables_to_dump = available_tables
    else:
        tables_to_dump = [t for t in dump_tables if t in available_tables]
    if not tables_to_dump:
        logger.warning("No tables to dump.")
        raise typer.Exit()

    progress = Progress(
        TimeElapsedColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    )
    panel = Panel(progress, title="Dumping tables", expand=False)
    with Live(panel), engine.connect() as connection:
        tables_task = progress.add_task("Overall progress", total=len(tables_to_dump))
        for table_name in tables_to_dump:
            pk_constraint = inspector.get_pk_constraint(table_name)
            pk_columns = pk_constraint.get("constrained_columns", [])
            if not pk_columns:
                logger.warning(f"Table '{table_name}' has no primary key, skipping.")
                progress.update(tables_task, advance=1)
                continue

            count_result = connection.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            )
            row_count = count_result.scalar()
            if row_count == 0:
                progress.update(tables_task, advance=1)
                continue

            table_task = progress.add_task(f"{table_name}", total=row_count)
            result = connection.execute(text(f"SELECT * FROM {table_name}"))
            column_names = list(result.keys())
            # SQLite stores all nested objects as JSON strings that we need to parse back to objects
            columns_info = inspector.get_columns(table_name)
            json_columns = {
                col["name"] for col in columns_info if "JSON" in str(col["type"])
            }

            for row in result:
                row_dict = dict(zip(column_names, row))
                # try to parse JSON strings back to nested objects
                for col_name in json_columns:
                    if col_name in row_dict and row_dict[col_name] is not None:
                        if isinstance(row_dict[col_name], str):
                            with suppress(Exception):
                                row_dict[col_name] = loads(row_dict[col_name])
                for ignored_col in ignored:
                    row_dict.pop(ignored_col, None)
                pk_values = [str(row_dict[pk]) for pk in pk_columns]
                file_path = output_directory / table_name
                if len(pk_values) > 1:
                    file_path = file_path / Path(*pk_values[:-1])
                file_path = file_path / f"{pk_values[-1]}.json"
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "w") as f:
                    json_dump(row_dict, f, indent=2)
                progress.update(table_task, advance=1)
            progress.update(tables_task, advance=1)

    logger.info(f"Dumped {len(tables_to_dump)} table(s) to '{output_directory}'")


@cli.command()
def pull(
    connection_string: options.connection_string = "sqlite:///sc-data-all.db",
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
        set_global_params(
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

        # alembic upgrade to ensure using the most recent version of the schemas
        engine = create_engine(
            connection_string,
            json_serializer=custom_serializer,
            pool_pre_ping=True,
        )
        with engine.begin() as connection:
            command.upgrade(alembic_cfg(connection, force_logging=False), "heads")

        with Session(engine) as session:
            # add/merge static objects to database
            for compliance_framework in compliance_frameworks.values():
                session.merge(compliance_framework)
            logger.info("%d Compliance Frameworks synced." % len(compliance_frameworks))
            for country in countries.values():
                session.merge(country)
            logger.info("%d Countries synced." % len(countries))
            for benchmark in benchmarks:
                session.merge(benchmark)
            logger.info("%d Benchmarks synced." % len(benchmarks))
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
                if Records.regions in records:
                    vendor.inventory_regions()
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
