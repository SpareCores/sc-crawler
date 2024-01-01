from sqlmodel import Session

from .database import create_db_and_tables, engine
from .vendors import aws


def crawl():
    create_db_and_tables()
    with Session(engine) as session:
        session.add(aws)
        session.commit()


if __name__ == "__main__":
    crawl()
