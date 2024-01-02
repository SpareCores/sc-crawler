from sqlmodel import Session

from .database import create_db_and_tables, engine
from .vendors import aws


def crawl():
    create_db_and_tables()
    with Session(engine) as session:
        # fill lookup tables? might not be needed due to autofill of downstream
        # TODO check country
        for vendor in [aws]:
            vendor.get_datacenters()
            session.add(vendor)
            session.commit()


if __name__ == "__main__":
    crawl()
