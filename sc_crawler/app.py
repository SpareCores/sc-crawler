from sqlmodel import Session

from .database import create_db_and_tables, engine
from .vendors import aws

# enable caching
from cachier import set_default_params

set_default_params(caching_enabled=True)


def crawl():
    create_db_and_tables()
    with Session(engine) as session:
        for vendor in [aws]:
            vendor.get_datacenters()
            vendor.get_zones()
            vendor.get_instance_types()
            session.add(vendor)
            session.commit()


if __name__ == "__main__":
    crawl()
