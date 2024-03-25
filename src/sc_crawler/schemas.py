"""Schemas for vendors, datacenters, zones, and other resources."""

import logging
from datetime import datetime
from enum import Enum
from hashlib import sha1
from importlib import import_module
from json import dumps
from types import ModuleType
from typing import List, Optional, Union

from pydantic import (
    BaseModel,
    ImportString,
    PrivateAttr,
)
from rich.progress import Progress
from sqlalchemy import ForeignKeyConstraint, update
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import declared_attr
from sqlmodel import JSON, Field, Relationship, Session, SQLModel, select

from .logger import VendorProgressTracker, log_start_end, logger
from .str import snake_case

# ##############################################################################
# SQLModel data and model extensions


class ScMetaModel(SQLModel.__class__):
    """Custom class factory to auto-update table models.

    - Reuse description of the table and its fields as SQL comment.

        Checking if the table and its fields have explicit comment set
        to be shown in the `CREATE TABLE` statements, and if not,
        reuse the optional table and field descriptions. Table
        docstrings are truncated to first line.

    - Reuse description of the fields to dynamically append to the
        docstring in the Attributes section.

    - Set __validator__ to the parent Pydantic model without set
        `table=True` for validations. This is found by the parent
        class' name ending in "Base".

    - Auto-generate SCD table docs from the non-SCD table docs.
    """

    def __init__(subclass, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # early return for non-tables
        if subclass.model_config.get("table") is None:
            return
        satable = subclass.metadata.tables[subclass.__tablename__]

        # generate docstring for SCD tables
        if subclass.__name__.endswith("Scd"):
            nonscd = [t for t in tables if t.__name__ == subclass.__name__[:-3]][0]
            doclines = nonscd.__doc__.splitlines()
            # drop trailing dot and append SCD
            doclines[0] = doclines[0][:-1] + " (SCD Type 2)."
            subclass.__doc__ = "\n".join(doclines)
        else:
            # describe table columns as attributes in docstring
            subclass.__doc__ = subclass.__doc__ + "\n\nAttributes:\n"
            for k, v in subclass.model_fields.items():
                if not hasattr(v.annotation, "__args__"):
                    typehint = v.annotation.__name__
                else:
                    typehint = str(v.annotation)
                description = satable.columns[k].comment
                subclass.__doc__ = (
                    subclass.__doc__ + f"    {k} ({typehint}): {description}\n"
                )

        # table comment
        if subclass.__doc__ and satable.comment is None:
            satable.comment = subclass.__doc__.splitlines()[0]

        # column comments
        for k, v in subclass.model_fields.items():
            comment = satable.columns[k].comment
            if v.description and comment is None:
                satable.columns[k].comment = v.description

        # find Pydantic model parent to be used for validating
        subclass.__validator__ = [
            m for m in subclass.__bases__ if m.__name__.endswith("Base")
        ][0]


class ScModel(SQLModel, metaclass=ScMetaModel):
    """Custom extensions to SQLModel objects and tables.

    Extra features:

    - auto-generated table names using snake_case,
    - support for hashing table rows,
    - reuse description field of tables/columns as SQL comment,
    - reuse description field of columns to extend the Attributes section of the docstring.
    """

    @declared_attr  # type: ignore
    def __tablename__(cls) -> str:
        """Generate tables names using all-lowercase snake_case."""
        return snake_case(cls.__name__)

    @classmethod
    def get_columns(cls) -> List[str]:
        """Return the table's column names in a dict for all, primary keys, and attributes."""
        columns = cls.__table__.columns.keys()
        pks = [pk.name for pk in inspect(cls).primary_key]
        attributes = [a for a in columns if a not in set(pks)]
        return {"all": columns, "primary_keys": pks, "attributes": attributes}

    @classmethod
    def get_table_name(cls) -> str:
        """Return the SQLModel object's table name."""
        return str(cls.__tablename__)

    @classmethod
    def get_validator(cls) -> Union["ScModel", None]:
        """Return the parent Base Pydantic model (without a table definition)."""
        if cls.model_config.get("table") is None:
            return None
        return cls.__validator__

    @classmethod
    def get_scd(cls) -> Union["ScModel", None]:
        """Return the SCD version of the SQLModel table."""
        if cls.model_config.get("table") is None:
            return None
        from .scd import scd_tables

        validator = cls.get_validator()
        scds = [t for t in scd_tables if t.get_validator() == validator]
        if len(scds) != 1:
            raise ValueError("Not found SCD definition.")
        return scds[0]

    @classmethod
    def hash(
        cls,
        session: Session,
        ignored: List[str] = ["observed_at"],
        progress: Optional[Progress] = None,
    ) -> dict:
        """Hash the content of the rows.

        Args:
            session: Database connection to use for object lookups.
            ignored: List of column names to exclude from hashing.
            progress: Optional progress bar to track the status of the hashing.

        Returns:
            Dictionary of the row hashes keyed by the JSON dump of primary keys.
        """
        pks = sorted(cls.get_columns()["primary_keys"])
        rows = session.exec(statement=select(cls))
        if progress:
            table_task_id = progress.add_task(
                cls.get_table_name(),
                total=session.query(cls).count(),
            )
        # no use of a generator as will need to serialize to JSON anyway
        hashes = {}
        for row in rows:
            # NOTE Pydantic is warning when read Gpu/Storage as dict
            # https://github.com/tiangolo/sqlmodel/issues/63#issuecomment-1081555082
            rowdict = row.model_dump(warnings=False)
            keys = {pk: rowdict.get(pk) for pk in pks}
            keys_id = dumps(keys, sort_keys=True)
            for dropkey in [*ignored, *pks]:
                rowdict.pop(dropkey, None)
            rowhash = sha1(dumps(rowdict, sort_keys=True).encode()).hexdigest()
            hashes[keys_id] = rowhash
            if progress:
                progress.update(table_task_id, advance=1)

        return hashes


class Json(BaseModel):
    """Custom base SQLModel class that supports dumping as JSON."""

    def __json__(self):
        return self.model_dump()


# ##############################################################################
# Enumerations, JSON nested data objects & other helper classes used in SC models


class Status(str, Enum):
    """Status, e.g. active or inactive."""

    ACTIVE = "active"
    INACTIVE = "inactive"


class Cpu(Json):
    """CPU details."""

    manufacturer: Optional[str] = None
    family: Optional[str] = None
    model: Optional[str] = None
    cores: Optional[int] = None
    threads: Optional[int] = None
    l1_cache_size: Optional[int] = None  # byte
    l2_cache_size: Optional[int] = None  # byte
    l3_cache_size: Optional[int] = None  # byte
    microcode: Optional[str] = None
    capabilities: List[str] = []
    bugs: List[str] = []
    bogomips: Optional[float] = None


class Gpu(Json):
    """GPU accelerator details."""

    manufacturer: str
    name: str
    memory: int  # MiB
    firmware: Optional[str] = None


class StorageType(str, Enum):
    """Type of a storage, e.g. HDD or SSD."""

    HDD = "hdd"
    SSD = "ssd"
    NVME_SSD = "nvme ssd"
    NETWORK = "network"


class Disk(Json):
    """Disk definition based on size and storage type."""

    size: int = 0  # GiB
    storage_type: StorageType


class TrafficDirection(str, Enum):
    """Directio of the network traffic."""

    IN = "inbound"
    OUT = "outbound"


class CpuAllocation(str, Enum):
    """CPU allocation methods at cloud vendors."""

    SHARED = "Shared"
    BURSTABLE = "Burstable"
    DEDICATED = "Dedicated"


class CpuArchitecture(str, Enum):
    """CPU architectures."""

    ARM64 = "arm64"
    ARM64_MAC = "arm64_mac"
    I386 = "i386"
    X86_64 = "x86_64"
    X86_64_MAC = "x86_64_mac"


class Allocation(str, Enum):
    """Server allocation options."""

    ONDEMAND = "ondemand"
    RESERVED = "reserved"
    SPOT = "spot"


class PriceUnit(str, Enum):
    """Supported units for the price tables."""

    YEAR = "year"
    MONTH = "month"
    HOUR = "hour"
    GIB = "GiB"
    GB = "GB"
    GB_MONTH = "GB/month"


class PriceTier(Json):
    """Price tier definition.

    As standard JSON does not support Inf, NaN etc values,
    thouse should be passed as string, e.g. for the upper bound.

    See [float_inf_to_str][sc_crawler.utils.float_inf_to_str] for
    converting an inifinite numeric value into "Infinity"."""

    lower: Union[float, str]
    upper: Union[float, str]
    price: float


# ##############################################################################
# Tiny helper classes for the most commonly used fields to be inherited
#
# Unfortunately, inheriting is not always convenient due to the order of
# columns, so some below Fields are sometimes copy/pasted into models.


class MetaColumns(ScModel):
    """Helper class to add the `status` and `observed_at` columns."""

    status: Status = Field(
        default=Status.ACTIVE,
        description="Status of the resource (active or inactive).",
    )
    observed_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        description="Timestamp of the last observation.",
    )


class HasComplianceFrameworkIdPK(ScModel):
    compliance_framework_id: str = Field(
        primary_key=True, description="Unique identifier."
    )


class HasVendorIdPK(ScModel):
    vendor_id: str = Field(primary_key=True, description="Unique identifier.")


class HasDatacenterIdPK(ScModel):
    datacenter_id: str = Field(
        primary_key=True, description="Unique identifier, as called at the Vendor."
    )


class HasZoneIdPK(ScModel):
    zone_id: str = Field(
        primary_key=True, description="Unique identifier, as called at the Vendor."
    )


class HasStorageIdPK(ScModel):
    storage_id: str = Field(
        primary_key=True, description="Unique identifier, as called at the Vendor."
    )


class HasServerIdPK(ScModel):
    server_id: str = Field(
        primary_key=True, description="Unique identifier, as called at the Vendor."
    )


class HasName(ScModel):
    name: str = Field(description="Human-friendly name.")


class HasDescription(ScModel):
    description: Optional[str] = Field(description="Short description.")


class HasVendorPKFK(ScModel):
    vendor_id: str = Field(
        foreign_key="vendor",
        primary_key=True,
        description="Reference to the Vendor.",
    )


class HasDatacenterPK(ScModel):
    datacenter_id: str = Field(
        primary_key=True,
        description="Reference to the Datacenter.",
    )


class HasZonePK(ScModel):
    zone_id: str = Field(primary_key=True, description="Reference to the Zone.")


class HasServerPK(ScModel):
    server_id: str = Field(
        primary_key=True,
        description="Reference to the Server.",
    )


class HasStoragePK(ScModel):
    storage_id: str = Field(
        primary_key=True,
        description="Reference to the Storage.",
    )


class HasPriceFieldsBase(ScModel):
    unit: PriceUnit = Field(description="Billing unit of the pricing model.")
    # set to max price if tiered
    price: float = Field(description="Actual price of a billing unit.")
    # e.g. setup fee for dedicated servers,
    # or upfront costs of a reserved instance type
    price_upfront: float = Field(
        default=0, description="Price to be paid when setting up the resource."
    )
    price_tiered: List[PriceTier] = Field(
        default=[],
        sa_type=JSON,
        description="List of pricing tiers with min/max thresholds and actual prices.",
    )
    currency: str = Field(default="USD", description="Currency of the prices.")


class HasPriceFields(MetaColumns, HasPriceFieldsBase):
    pass


# ##############################################################################
# Actual SC data schemas and model definitions


class CountryFields(ScModel):
    country_id: str = Field(
        primary_key=True,
        description="Country code by ISO 3166 alpha-2.",
    )
    continent: str = Field(description="Continent name.")


class CountryBase(MetaColumns, CountryFields):
    pass


class Country(CountryBase, table=True):
    """Country and continent mapping."""

    vendors: List["Vendor"] = Relationship(back_populates="country")
    datacenters: List["Datacenter"] = Relationship(back_populates="country")


class ComplianceFrameworkFields(ScModel):
    abbreviation: Optional[str] = Field(
        description="Short abbreviation of the Framework name."
    )
    description: Optional[str] = Field(
        description=(
            "Description of the framework in a few paragrahs, "
            "outlining key features and characteristics for reference."
        )
    )
    # TODO HttpUrl not supported by SQLModel
    # TODO upload to cdn.sparecores.com (s3/cloudfront)
    logo: Optional[str] = Field(
        default=None,
        description="Publicly accessible URL to the image of the Framework's logo.",
    )
    # TODO HttpUrl not supported by SQLModel
    homepage: Optional[str] = Field(
        default=None,
        description="Public homepage with more information on the Framework.",
    )


class ComplianceFrameworkBase(
    MetaColumns, ComplianceFrameworkFields, HasName, HasComplianceFrameworkIdPK
):
    pass


class ComplianceFramework(ComplianceFrameworkBase, table=True):
    """List of Compliance Frameworks, such as HIPAA or SOC 2 Type 1."""

    vendor_links: List["VendorComplianceLink"] = Relationship(
        back_populates="compliance_framework"
    )


class VendorFields(HasName, HasVendorIdPK):
    # TODO HttpUrl not supported by SQLModel
    # TODO upload to cdn.sparecores.com (s3/cloudfront)
    logo: Optional[str] = Field(
        default=None,
        description="Publicly accessible URL to the image of the Vendor's logo.",
    )
    # TODO HttpUrl not supported by SQLModel
    homepage: Optional[str] = Field(
        default=None,
        description="Public homepage of the Vendor.",
    )

    country_id: str = Field(
        foreign_key="country",
        description="Reference to the Country, where the Vendor's main headquarter is located.",
    )
    state: Optional[str] = Field(
        default=None,
        description="Optional state/administrative area of the Vendor's location within the Country.",
    )
    city: Optional[str] = Field(
        default=None, description="Optional city name of the Vendor's main location."
    )
    address_line: Optional[str] = Field(
        default=None, description="Optional address line of the Vendor's main location."
    )
    zip_code: Optional[str] = Field(
        default=None, description="Optional ZIP code of the Vendor's main location."
    )

    # https://dbpedia.org/ontology/Organisation
    founding_year: int = Field(description="4-digit year when the Vendor was founded.")

    # TODO HttpUrl not supported by SQLModel
    status_page: Optional[str] = Field(
        default=None, description="Public status page of the Vendor."
    )


class VendorBase(MetaColumns, VendorFields):
    pass


class Vendor(VendorBase, table=True):
    """Compute resource vendors, such as cloud and server providers.

    Examples:
        >>> from sc_crawler.schemas import Vendor
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
        """The VendorProgressTracker to use for updating progress bars."""
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

    def register_progress_tracker(self, progress_tracker: VendorProgressTracker):
        """Attach a VendorProgressTracker to use for updating progress bars."""
        self._progress_tracker = progress_tracker

    def set_table_rows_inactive(self, model: str, *args) -> None:
        """Set this vendor's records to INACTIVE in a table

        Positional arguments can be used to pass further filters
        (besides the default model.vendor_id filter) referencing the
        model object with SQLModel syntax, e.g.

        >>> aws.set_table_rows_inactive(ServerPrice, ServerPrice.price < 10)  # doctest: +SKIP
        """
        if self.session:
            query = update(model).where(model.vendor_id == self.vendor_id)
            for arg in args:
                query = query.where(arg)
            self.session.execute(query.values(status=Status.INACTIVE))

    @log_start_end
    def inventory_compliance_frameworks(self):
        """Get the vendor's all compliance frameworks."""
        self.set_table_rows_inactive(VendorComplianceLink)
        self._get_methods().inventory_compliance_frameworks(self)

    @log_start_end
    def inventory_datacenters(self):
        """Get the vendor's all datacenters."""
        self.set_table_rows_inactive(Datacenter)
        self._get_methods().inventory_datacenters(self)

    @log_start_end
    def inventory_zones(self):
        """Get all the zones in the vendor's datacenters."""
        self.set_table_rows_inactive(Zone)
        self._get_methods().inventory_zones(self)

    @log_start_end
    def inventory_servers(self):
        """Get the vendor's all server types."""
        self.set_table_rows_inactive(Server)
        self._get_methods().inventory_servers(self)

    @log_start_end
    def inventory_server_prices(self):
        """Get the current standard/ondemand/reserved prices of all server types."""
        self.set_table_rows_inactive(
            ServerPrice, ServerPrice.allocation != Allocation.SPOT
        )
        self._get_methods().inventory_server_prices(self)

    @log_start_end
    def inventory_server_prices_spot(self):
        """Get the current spot prices of all server types."""
        self.set_table_rows_inactive(
            ServerPrice, ServerPrice.allocation == Allocation.SPOT
        )
        self._get_methods().inventory_server_prices_spot(self)

    @log_start_end
    def inventory_storages(self):
        self.set_table_rows_inactive(Storage)
        self._get_methods().inventory_storages(self)

    @log_start_end
    def inventory_storage_prices(self):
        self.set_table_rows_inactive(StoragePrice)
        self._get_methods().inventory_storage_prices(self)

    @log_start_end
    def inventory_traffic_prices(self):
        self.set_table_rows_inactive(TrafficPrice)
        self._get_methods().inventory_traffic_prices(self)

    @log_start_end
    def inventory_ipv4_prices(self):
        self.set_table_rows_inactive(Ipv4Price)
        self._get_methods().inventory_ipv4_prices(self)


class VendorComplianceLinkFields(HasVendorPKFK):
    compliance_framework_id: str = Field(
        foreign_key="compliance_framework",
        primary_key=True,
        description="Reference to the Compliance Framework.",
    )
    comment: Optional[str] = Field(
        default=None,
        description="Optional references, such as dates, URLs, and additional information/evidence.",
    )


class VendorComplianceLinkBase(MetaColumns, VendorComplianceLinkFields):
    pass


class VendorComplianceLink(VendorComplianceLinkBase, table=True):
    """List of known Compliance Frameworks paired with vendors."""

    vendor: Vendor = Relationship(back_populates="compliance_framework_links")
    compliance_framework: ComplianceFramework = Relationship(
        back_populates="vendor_links"
    )


class DatacenterFields(HasName, HasDatacenterIdPK):
    aliases: List[str] = Field(
        default=[],
        sa_type=JSON,
        description="List of other commonly used names for the same Datacenter.",
    )

    vendor_id: str = Field(
        foreign_key="vendor",
        primary_key=True,
        description="Reference to the Vendor.",
    )

    country_id: str = Field(
        foreign_key="country",
        description="Reference to the Country, where the Datacenter is located.",
    )
    state: Optional[str] = Field(
        default=None,
        description="Optional state/administrative area of the Datacenter's location within the Country.",
    )
    city: Optional[str] = Field(
        default=None, description="Optional city name of the Datacenter's location."
    )
    address_line: Optional[str] = Field(
        default=None, description="Optional address line of the Datacenter's location."
    )
    zip_code: Optional[str] = Field(
        default=None, description="Optional ZIP code of the Datacenter's location."
    )

    founding_year: Optional[int] = Field(
        default=None, description="4-digit year when the Datacenter was founded."
    )
    green_energy: Optional[bool] = Field(
        default=None,
        description="If the Datacenter is 100% powered by renewable energy.",
    )


class DatacenterBase(MetaColumns, DatacenterFields):
    pass


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


class ZoneBase(MetaColumns, HasName, HasDatacenterPK, HasVendorPKFK, HasZoneIdPK):
    pass


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


class StorageFields(HasDescription, HasName, HasVendorPKFK, HasStorageIdPK):
    storage_type: StorageType = Field(
        description="High-level category of the storage, e.g. HDD or SDD."
    )
    max_iops: Optional[int] = Field(
        default=None, description="Maximum Input/Output Operations Per Second."
    )
    max_throughput: Optional[int] = Field(
        default=None, description="Maximum Throughput (MiB/s)."
    )
    min_size: Optional[int] = Field(
        default=None, description="Minimum required size (GiB)."
    )
    max_size: Optional[int] = Field(
        default=None, description="Maximum possible size (GiB)."
    )


class StorageBase(MetaColumns, StorageFields):
    pass


class Storage(StorageBase, table=True):
    """Flexible storage options that can be attached to a Server."""

    vendor: Vendor = Relationship(back_populates="storages")

    prices: List["StoragePrice"] = Relationship(
        back_populates="storage", sa_relationship_kwargs={"viewonly": True}
    )


class ServerFields(HasServerIdPK):
    vendor_id: str = Field(
        foreign_key="vendor",
        primary_key=True,
        description="Reference to the Vendor.",
    )
    name: str = Field(
        default=None,
        description="Human-friendly name or short description.",
    )
    vcpus: int = Field(
        default=None,
        description="Default number of virtual CPUs (vCPU) of the server.",
    )
    hypervisor: Optional[str] = Field(
        default=None,
        description="Hypervisor of the virtual server, e.g. Xen, KVM, Nitro or Dedicated.",
    )
    cpu_allocation: CpuAllocation = Field(
        default=None,
        description="Allocation of CPU(s) to the server, e.g. shared, burstable or dedicated.",
    )
    cpu_cores: int = Field(
        default=None,
        description=(
            "Default number of CPU cores of the server. "
            "Equals to vCPUs when HyperThreading is disabled."
        ),
    )
    cpu_speed: Optional[float] = Field(
        default=None, description="Vendor-reported maximum CPU clock speed (GHz)."
    )
    cpu_architecture: CpuArchitecture = Field(
        default=None,
        description="CPU architecture (arm64, arm64_mac, i386, or x86_64).",
    )
    cpu_manufacturer: Optional[str] = Field(
        default=None,
        description="The manufacturer of the primary processor, e.g. Intel or AMD.",
    )
    cpu_family: Optional[str] = Field(
        default=None,
        description="The product line/family of the primary processor, e.g. Xeon, Core i7, Ryzen 9.",
    )
    cpu_model: Optional[str] = Field(
        default=None,
        description="The model number of the primary processor, e.g. 9750H.",
    )
    cpus: List[Cpu] = Field(
        default=[],
        sa_type=JSON,
        description=(
            "JSON array of known CPU details, e.g. the manufacturer, family, model; "
            "L1/L2/L3 cache size; microcode version; feature flags; bugs etc."
        ),
    )
    memory: int = Field(
        default=None,
        description="RAM amount (MiB).",
    )
    gpu_count: int = Field(
        default=0,
        description="Number of GPU accelerator(s).",
    )
    gpu_memory_min: Optional[int] = Field(
        default=None,
        description="Memory (MiB) allocated to the lowest-end GPU accelerator.",
    )
    gpu_memory_total: Optional[int] = Field(
        default=None,
        description="Overall memory (MiB) allocated to all the GPU accelerator(s).",
    )
    gpu_manufacturer: Optional[str] = Field(
        default=None,
        description="The manufacturer of the primary GPU accelerator.",
    )
    gpu_model: Optional[str] = Field(
        default=None,
        description="The model number of the primary GPU accelerator.",
    )
    gpus: List[Gpu] = Field(
        default=[],
        sa_type=JSON,
        description=(
            "JSON array of GPU accelerator details, including "
            "the manufacturer, name, and memory (MiB) of each GPU."
        ),
    )
    storage_size: int = Field(
        default=0,
        description="Overall size (GB) of the disk(s).",
    )
    storage_type: Optional[StorageType] = Field(
        default=None,
        description="Primary disk type, e.g. HDD, SSD, NVMe SSD, or network).",
    )
    storages: List[Disk] = Field(
        default=[],
        sa_type=JSON,
        description=(
            "JSON array of disks attached to the server, including "
            "the size (MiB) and type of each disk."
        ),
    )
    network_speed: Optional[float] = Field(
        default=None,
        description="The baseline network performance (Gbps) of the network card.",
    )
    inbound_traffic: float = Field(
        default=0,
        description="Amount of complimentary inbound traffic (GB) per month.",
    )
    outbound_traffic: float = Field(
        default=0,
        description="Amount of complimentary outbound traffic (GB) per month.",
    )
    ipv4: int = Field(
        default=0, description="Number of complimentary IPv4 address(es)."
    )


class ServerBase(MetaColumns, ServerFields):
    pass


class Server(ServerBase, table=True):
    """Server types."""

    vendor: Vendor = Relationship(back_populates="servers")
    prices: List["ServerPrice"] = Relationship(
        back_populates="server", sa_relationship_kwargs={"viewonly": True}
    )


class ServerPriceFields(ScModel):
    operating_system: str = Field(description="Operating System.")
    allocation: Allocation = Field(
        default=Allocation.ONDEMAND,
        description="Allocation method, e.g. on-demand or spot.",
        primary_key=True,
    )


class ServerPriceBase(
    HasPriceFields,
    ServerPriceFields,
    HasServerPK,
    HasZonePK,
    HasDatacenterPK,
    HasVendorPKFK,
):
    pass


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


class StoragePriceBase(HasPriceFields, HasStoragePK, HasDatacenterPK, HasVendorPKFK):
    pass


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


class TrafficPriceFields(HasDatacenterPK, HasVendorPKFK):
    direction: TrafficDirection = Field(
        description="Direction of the traffic: inbound or outbound.",
        primary_key=True,
    )


class TrafficPriceBase(HasPriceFields, TrafficPriceFields):
    pass


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


class Ipv4PriceBase(HasPriceFields, HasDatacenterPK, HasVendorPKFK):
    pass


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
