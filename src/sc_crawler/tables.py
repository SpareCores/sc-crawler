"""Table definitions for vendors, datacenters, zones, and other cloud resources."""

import logging
from importlib import import_module
from types import ModuleType
from typing import Callable, List, Optional

from pydantic import ImportString, PrivateAttr
from sqlalchemy import ForeignKeyConstraint, update
from sqlmodel import Relationship, Session, SQLModel

from .insert import insert_items
from .logger import VendorProgressTracker, log_start_end, logger
from .table_bases import (
    ComplianceFrameworkBase,
    CountryBase,
    DatacenterBase,
    Ipv4PriceBase,
    ScModel,
    ServerBase,
    ServerPriceBase,
    StorageBase,
    StoragePriceBase,
    TrafficPriceBase,
    VendorBase,
    VendorComplianceLinkBase,
    ZoneBase,
)
from .table_fields import (
    Allocation,
    CpuAllocation,  # noqa: F401 imported for mkdocstrings
    CpuArchitecture,  # noqa: F401 imported for mkdocstrings
    PriceUnit,  # noqa: F401 imported for mkdocstrings
    Status,
    StorageType,  # noqa: F401 imported for mkdocstrings
    TrafficDirection,  # noqa: F401 imported for mkdocstrings
)


class Country(CountryBase, table=True):
    """Country and continent mapping."""

    vendors: List["Vendor"] = Relationship(back_populates="country")
    datacenters: List["Datacenter"] = Relationship(back_populates="country")


class ComplianceFramework(ComplianceFrameworkBase, table=True):
    """List of Compliance Frameworks, such as HIPAA or SOC 2 Type 1."""

    vendor_links: List["VendorComplianceLink"] = Relationship(
        back_populates="compliance_framework"
    )


class Vendor(VendorBase, table=True):
    """Compute resource vendors, such as cloud and server providers.

    Examples:
        >>> from sc_crawler.tables import Vendor
        >>> from sc_crawler.lookup import countries
        >>> aws = Vendor(vendor_id='aws', name='Amazon Web Services', homepage='https://aws.amazon.com', country=countries["US"], founding_year=2002)
        >>> aws
        Vendor(vendor_id='aws'...
        >>> from sc_crawler import vendors
        >>> vendors.aws
        Vendor(vendor_id='aws'...
    """  # noqa: E501

    compliance_framework_links: List["VendorComplianceLink"] = Relationship(
        back_populates="vendor"
    )
    country: Country = Relationship(back_populates="vendors")
    datacenters: List["Datacenter"] = Relationship(
        back_populates="vendor", sa_relationship_kwargs={"viewonly": True}
    )
    zones: List["Zone"] = Relationship(
        back_populates="vendor", sa_relationship_kwargs={"viewonly": True}
    )
    storages: List["Storage"] = Relationship(
        back_populates="vendor", sa_relationship_kwargs={"viewonly": True}
    )
    servers: List["Server"] = Relationship(
        back_populates="vendor", sa_relationship_kwargs={"viewonly": True}
    )
    server_prices: List["ServerPrice"] = Relationship(
        back_populates="vendor", sa_relationship_kwargs={"viewonly": True}
    )
    traffic_prices: List["TrafficPrice"] = Relationship(
        back_populates="vendor", sa_relationship_kwargs={"viewonly": True}
    )
    ipv4_prices: List["Ipv4Price"] = Relationship(
        back_populates="vendor", sa_relationship_kwargs={"viewonly": True}
    )
    storage_prices: List["StoragePrice"] = Relationship(
        back_populates="vendor", sa_relationship_kwargs={"viewonly": True}
    )

    # private attributes
    _methods: Optional[ImportString[ModuleType]] = PrivateAttr(default=None)
    _session: Optional[Session] = PrivateAttr()
    _progress_tracker: Optional[VendorProgressTracker] = PrivateAttr()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # SQLModel does not validates pydantic typing,
        # only when writing to DB (much later in the process)
        if not self.vendor_id:
            raise ValueError("No vendor id provided")
        if not self.name:
            raise ValueError("No vendor name provided")
        if not self.homepage:
            raise ValueError("No vendor homepage provided")
        if not self.country:
            raise ValueError("No vendor country provided")
        # make sure methods are provided
        methods = self._get_methods().__dir__()
        for method in [
            "inventory_compliance_frameworks",
            "inventory_datacenters",
            "inventory_zones",
            "inventory_servers",
            "inventory_server_prices",
            "inventory_server_prices_spot",
            "inventory_storage_prices",
            "inventory_traffic_prices",
            "inventory_ipv4_prices",
        ]:
            if method not in methods:
                raise NotImplementedError(
                    f"Unsupported '{self.vendor_id}' vendor: missing '{method}' method."
                )

    def _get_methods(self):
        # private attributes are not (always) initialized correctly by SQLmodel
        # e.g. the attribute is missing alltogether when loaded from DB
        # https://github.com/tiangolo/sqlmodel/issues/149
        try:
            hasattr(self, "_methods")
        except Exception:
            self._methods = None
        if not self._methods:
            try:
                vendor_module = ".".join(
                    [__name__.split(".", maxsplit=1)[0], "vendors", self.vendor_id]
                )
                self._methods = import_module(vendor_module)
            except Exception as exc:
                raise NotImplementedError(
                    f"Unsupported '{self.vendor_id}' vendor: no methods defined."
                ) from exc
        return self._methods

    @property
    def session(self):
        """The Session to use for merging dependent objects into the database."""
        try:
            return self._session
        except Exception:
            return None

    @session.setter
    def session(self, session: Session):
        self._session = session

    @session.deleter
    def session(self):
        self._session = None

    @property
    def progress_tracker(self):
        """The [sc_crawler.logger.VendorProgressTracker][] to use for updating progress bars."""
        return self._progress_tracker

    @progress_tracker.setter
    def progress_tracker(self, progress_tracker: VendorProgressTracker):
        self._progress_tracker = progress_tracker

    @progress_tracker.deleter
    def progress_tracker(self):
        self._progress_tracker = None

    @property
    def tasks(self):
        """Reexport progress_tracker.tasks for easier access."""
        return self._progress_tracker.tasks

    def log(self, message: str, level: int = logging.INFO):
        logger.log(level, self.name + ": " + message, stacklevel=2)

    def set_table_rows_inactive(self, model: str, *args) -> None:
        """Set this vendor's records to [INACTIVE][sc_crawler.table_fields.Status] in a table.

        Positional arguments can be used to pass further filters
        (besides the default model.vendor_id filter) referencing the
        model object with SQLModel syntax.

        Examples:
            >>> aws.set_table_rows_inactive(ServerPrice, ServerPrice.price < 10)  # doctest: +SKIP
        """
        if self.session:
            query = update(model).where(model.vendor_id == self.vendor_id)
            for arg in args:
                query = query.where(arg)
            self.session.execute(query.values(status=Status.INACTIVE))

    def _inventory(self, table: ScModel, inventory: Callable):
        """Mark all rows in a table inactive, then insert new/updated items."""
        self.set_table_rows_inactive(table)
        insert_items(table, inventory(self), self)

    @log_start_end
    def inventory_compliance_frameworks(self):
        """Get the vendor's all compliance frameworks."""
        self._inventory(
            VendorComplianceLink, self._get_methods().inventory_compliance_frameworks
        )

    @log_start_end
    def inventory_datacenters(self):
        """Get the vendor's all datacenters."""
        self._inventory(Datacenter, self._get_methods().inventory_datacenters)

    @log_start_end
    def inventory_zones(self):
        """Get all the zones in the vendor's datacenters."""
        self._inventory(Zone, self._get_methods().inventory_zones)

    @log_start_end
    def inventory_servers(self):
        """Get the vendor's all server types."""
        self._inventory(Server, self._get_methods().inventory_servers)

    @log_start_end
    def inventory_server_prices(self):
        """Get the current standard/ondemand/reserved prices of all server types."""
        self.set_table_rows_inactive(
            ServerPrice, ServerPrice.allocation != Allocation.SPOT
        )
        insert_items(
            ServerPrice,
            self._get_methods().inventory_server_prices(self),
            self,
            prefix="ondemand",
        )

    @log_start_end
    def inventory_server_prices_spot(self):
        """Get the current spot prices of all server types."""
        self.set_table_rows_inactive(
            ServerPrice, ServerPrice.allocation == Allocation.SPOT
        )
        insert_items(
            ServerPrice,
            self._get_methods().inventory_server_prices_spot(self),
            self,
            prefix="ondemand",
        )

    @log_start_end
    def inventory_storages(self):
        self._inventory(Storage, self._get_methods().inventory_storages)

    @log_start_end
    def inventory_storage_prices(self):
        self._inventory(StoragePrice, self._get_methods().inventory_storage_prices)

    @log_start_end
    def inventory_traffic_prices(self):
        self._inventory(TrafficPrice, self._get_methods().inventory_traffic_prices)

    @log_start_end
    def inventory_ipv4_prices(self):
        self._inventory(Ipv4Price, self._get_methods().inventory_ipv4_prices)


class VendorComplianceLink(VendorComplianceLinkBase, table=True):
    """List of known Compliance Frameworks paired with vendors."""

    vendor: Vendor = Relationship(back_populates="compliance_framework_links")
    compliance_framework: ComplianceFramework = Relationship(
        back_populates="vendor_links"
    )


class Datacenter(DatacenterBase, table=True):
    """Datacenters/regions of Vendors."""

    vendor: Vendor = Relationship(back_populates="datacenters")
    country: Country = Relationship(back_populates="datacenters")

    zones: List["Zone"] = Relationship(
        back_populates="datacenter", sa_relationship_kwargs={"viewonly": True}
    )
    server_prices: List["ServerPrice"] = Relationship(
        back_populates="datacenter", sa_relationship_kwargs={"viewonly": True}
    )
    traffic_prices: List["TrafficPrice"] = Relationship(
        back_populates="datacenter", sa_relationship_kwargs={"viewonly": True}
    )
    ipv4_prices: List["Ipv4Price"] = Relationship(
        back_populates="datacenter", sa_relationship_kwargs={"viewonly": True}
    )
    storage_prices: List["StoragePrice"] = Relationship(
        back_populates="datacenter", sa_relationship_kwargs={"viewonly": True}
    )


class Zone(ZoneBase, table=True):
    """Availability zones of Datacenters."""

    __table_args__ = (
        ForeignKeyConstraint(
            ["vendor_id", "datacenter_id"],
            ["datacenter.vendor_id", "datacenter.datacenter_id"],
        ),
    )

    datacenter: Datacenter = Relationship(
        back_populates="zones",
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(Datacenter.datacenter_id == foreign(Zone.datacenter_id), "
                "Vendor.vendor_id == foreign(Zone.vendor_id))"
            )
        },
    )
    vendor: Vendor = Relationship(back_populates="zones")

    server_prices: List["ServerPrice"] = Relationship(
        back_populates="zone", sa_relationship_kwargs={"viewonly": True}
    )


class Storage(StorageBase, table=True):
    """Flexible storage options that can be attached to a Server."""

    vendor: Vendor = Relationship(back_populates="storages")

    prices: List["StoragePrice"] = Relationship(
        back_populates="storage", sa_relationship_kwargs={"viewonly": True}
    )


class Server(ServerBase, table=True):
    """Server types."""

    vendor: Vendor = Relationship(back_populates="servers")
    prices: List["ServerPrice"] = Relationship(
        back_populates="server", sa_relationship_kwargs={"viewonly": True}
    )


class ServerPrice(ServerPriceBase, table=True):
    """Server type prices per Datacenter and Allocation method."""

    __table_args__ = (
        ForeignKeyConstraint(
            ["vendor_id", "datacenter_id"],
            ["datacenter.vendor_id", "datacenter.datacenter_id"],
        ),
        ForeignKeyConstraint(
            ["vendor_id", "datacenter_id", "zone_id"],
            ["zone.vendor_id", "zone.datacenter_id", "zone.zone_id"],
        ),
        ForeignKeyConstraint(
            ["vendor_id", "server_id"],
            ["server.vendor_id", "server.server_id"],
        ),
    )
    vendor: Vendor = Relationship(back_populates="server_prices")
    datacenter: Datacenter = Relationship(
        back_populates="server_prices",
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(Datacenter.datacenter_id == foreign(ServerPrice.datacenter_id), "
                "Vendor.vendor_id == foreign(ServerPrice.vendor_id))"
            )
        },
    )
    zone: Zone = Relationship(
        back_populates="server_prices",
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(Zone.zone_id == foreign(ServerPrice.zone_id), "
                "Datacenter.datacenter_id == foreign(ServerPrice.datacenter_id),"
                "Vendor.vendor_id == foreign(ServerPrice.vendor_id))"
            )
        },
    )
    server: Server = Relationship(
        back_populates="prices",
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(Server.server_id == foreign(ServerPrice.server_id), "
                "Vendor.vendor_id == foreign(ServerPrice.vendor_id))"
            )
        },
    )


class StoragePrice(StoragePriceBase, table=True):
    """Flexible Storage prices in each Datacenter."""

    __table_args__ = (
        ForeignKeyConstraint(
            ["vendor_id", "datacenter_id"],
            ["datacenter.vendor_id", "datacenter.datacenter_id"],
        ),
        ForeignKeyConstraint(
            ["vendor_id", "storage_id"],
            ["storage.vendor_id", "storage.storage_id"],
        ),
    )
    vendor: Vendor = Relationship(back_populates="storage_prices")
    datacenter: Datacenter = Relationship(
        back_populates="storage_prices",
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(Datacenter.datacenter_id == foreign(StoragePrice.datacenter_id),"
                "Vendor.vendor_id == foreign(StoragePrice.vendor_id))"
            )
        },
    )
    storage: Storage = Relationship(
        back_populates="prices",
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(Storage.storage_id == foreign(StoragePrice.storage_id), "
                "Vendor.vendor_id == foreign(StoragePrice.vendor_id))"
            )
        },
    )


class TrafficPrice(TrafficPriceBase, table=True):
    """Extra Traffic prices in each Datacenter."""

    __table_args__ = (
        ForeignKeyConstraint(
            ["vendor_id", "datacenter_id"],
            ["datacenter.vendor_id", "datacenter.datacenter_id"],
        ),
    )
    vendor: Vendor = Relationship(back_populates="traffic_prices")
    datacenter: Datacenter = Relationship(
        back_populates="traffic_prices",
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(Datacenter.datacenter_id == foreign(TrafficPrice.datacenter_id),"
                "Vendor.vendor_id == foreign(TrafficPrice.vendor_id))"
            )
        },
    )


class Ipv4Price(Ipv4PriceBase, table=True):
    """Price of an IPv4 address in each Datacenter."""

    __table_args__ = (
        ForeignKeyConstraint(
            ["vendor_id", "datacenter_id"],
            ["datacenter.vendor_id", "datacenter.datacenter_id"],
        ),
    )
    vendor: Vendor = Relationship(back_populates="ipv4_prices")
    datacenter: Datacenter = Relationship(
        back_populates="ipv4_prices",
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(Datacenter.datacenter_id == foreign(Ipv4Price.datacenter_id),"
                "Vendor.vendor_id == foreign(Ipv4Price.vendor_id))"
            )
        },
    )


Country.model_rebuild()
ComplianceFramework.model_rebuild()
Vendor.model_rebuild()
VendorComplianceLink.model_rebuild()
Datacenter.model_rebuild()
Zone.model_rebuild()
Storage.model_rebuild()
Server.model_rebuild()


def is_table(table):
    try:
        return table.model_config["table"] is True
    except Exception:
        return False


tables: List[SQLModel] = [o for o in globals().values() if is_table(o)]
"""List of all SQLModel (table) models."""
