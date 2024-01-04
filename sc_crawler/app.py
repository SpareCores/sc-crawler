import logging

from cachier import set_default_params
from sqlmodel import Session

from .database import create_db_and_tables, engine
from .logger import logger
from .vendors import aws

# enable caching
set_default_params(caching_enabled=True)

# enable logging
ch = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
ch.setFormatter(formatter)
logger.setLevel(logging.DEBUG)
logger.addHandler(ch)


def crawl():
    create_db_and_tables()
    with Session(engine) as session:
        for vendor in [aws]:
            vendor.get_all()
            session.add(vendor)
            session.commit()


if __name__ == "__main__":
    crawl()
