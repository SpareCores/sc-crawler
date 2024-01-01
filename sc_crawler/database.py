from os import getenv
from sqlmodel import SQLModel, create_engine


DB_ENGINE = getenv("SC_CRAWLER_DB_ENGINE", "sqlite:////tmp/sc_crawler.db")
engine = create_engine(DB_ENGINE)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
