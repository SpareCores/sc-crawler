from sqlmodel import Session

from .database import create_db_and_tables, engine
from .vendors import aws


def crawl():
    create_db_and_tables()
    with Session(engine) as session:
        for vendor in [aws]:
            vendor.get_datacenters()
            vendor.get_zones()
            session.add(vendor)
            session.commit()


if __name__ == "__main__":
    crawl()
