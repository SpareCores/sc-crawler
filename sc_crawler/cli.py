import logging
from enum import Enum
from json import dumps

import typer
from cachier import set_default_params
from sqlmodel import Session, SQLModel, create_engine
from typing_extensions import Annotated

from .logger import logger
from .vendors import aws

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


@cli.command()
def schema(dialect: Engines):
    """
    Print the database schema in a SQL dialect.
    """
    url = engine_to_dialect[dialect.value]

    def metadata_dump(sql, *_args, **_kwargs):
        typer.echo(sql.compile(dialect=engine.dialect))

    engine = create_engine(url, strategy="mock", executor=metadata_dump)
    SQLModel.metadata.create_all(engine)


@cli.command()
def pull(
    connection_string: Annotated[
        str, typer.Option(help="Database URL with SQLAlchemy dialect.")
    ] = "sqlite:///sc_crawler.db",
    log_level: Annotated[LogLevels, typer.Option(help="Log level threshold.")] = "INFO",
):
    """
    Pull data from available vendor APIs and store in a database.
    """

    def custom_serializer(x):
        """Use JSON serializer defined in custom objects."""
        return dumps(x, default=lambda x: x.__json__())

    # enable caching
    set_default_params(caching_enabled=True)

    # enable logging
    channel = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    channel.setFormatter(formatter)
    logger.setLevel(log_level.value)
    logger.addHandler(channel)

    engine = create_engine(connection_string, json_serializer=custom_serializer)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        for vendor in [aws]:
            vendor.get_all()
            session.add(vendor)
            session.commit()


if __name__ == "__main__":
    pull()
