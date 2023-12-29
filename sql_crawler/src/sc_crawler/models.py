from typing import Optional, List
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine, DateTime, ForeignKey, String, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, sessionmaker, validates
import datetime
import os
import functools
import validators

DB_ENGINE = os.getenv("SC_CRAWLER_DB_ENGINE", "sqlite:////tmp/sc_crawler.db")

Base = declarative_base()
metadata = Base.metadata


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    logo_url: Mapped[Optional[str]] = mapped_column(String(256), unique=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=func.now(), nullable=False)
    datacenters: Mapped[List["Datacenter"]] = relationship()

    def __repr__(self):
        return f"id: {self.id}, name: {self.name}"

    @validates("logo_url")
    def validate_url(self, k, url):
        res = validators.url(url)
        if res:
            return url
        raise res


class Datacenter(Base):
    __tablename__ = "datacenters"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.id", primary_key=True))
    name: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)


@functools.cache
def db_engine():
    return create_engine(DB_ENGINE, echo=True)


@functools.cache
def db_session():
    return sessionmaker(bind=db_engine())


def init_db():
    metadata.create_all(db_engine())
