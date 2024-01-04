from cachier import set_default_params
import logging
from sqlmodel import Session

from .database import create_db_and_tables, engine
from .logger import logger
from .vendors import aws

# enable caching
set_default_params(caching_enabled=True)

# enable logging
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter)
logger.addHandler(ch)


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
