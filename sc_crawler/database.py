from json import dumps
from os import getenv

from sqlmodel import SQLModel, create_engine


def custom_serializer(x):
    """Use JSON serializer defined in custom objects."""
    return dumps(x, default=lambda x: x.__json__())


DB_ENGINE = getenv("SC_CRAWLER_DB_ENGINE", "sqlite:////tmp/sc_crawler.db")
engine = create_engine(DB_ENGINE, json_serializer=custom_serializer)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
