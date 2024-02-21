"""Schemas for vendors, datacenters, zones, and other resources."""


from datetime import datetime
from enum import Enum
from hashlib import sha1
from importlib import import_module
from json import dumps
from types import ModuleType
from typing import List, Optional

from pydantic import (
    BaseModel,
    ImportString,
    PrivateAttr,
)
from sqlalchemy import DateTime
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import declared_attr
from sqlmodel import JSON, Column, Field, Relationship, Session, SQLModel, select

from .logger import logger, log_start_end
from .str import snake_case


class ScMetaModel(SQLModel.__class__):
    """Custom class factory to auto-update table models.

    - Reuse description of the table and its fields as SQL comment.

        Checking if the table and its fields have explicit comment set
        to be shown in the `CREATE TABLE` statements, and if not,
        reuse the optional table and field descriptions. Table
        docstrings are truncated to first line.

    - Append observed_at column.
    """

    def __init__(subclass, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # early return for non-tables
        if subclass.model_config.get("table") is None:
            return
        # table comment
        satable = subclass.metadata.tables[subclass.__tablename__]
        if subclass.__doc__ and satable.comment is None:
            satable.comment = subclass.__doc__.splitlines()[0]
        # column comments
        for k, v in subclass.model_fields.items():
            comment = satable.columns[k].comment
            if v.description and comment is None:
                satable.columns[k].comment = v.description
        # append observed_at as last column
        satable.append_column(
            Column(
                "observed_at",
                DateTime,
                default=datetime.utcnow,
                onupdate=datetime.utcnow,
            )
        )


class ScModel(SQLModel, metaclass=ScMetaModel):
    """Custom extensions to SQLModel objects and tables.

    Extra features:
    - auto-generated table names using snake_case,
    - support for hashing table rows,
    - reuse description field of tables/columns as SQL comment,
    - automatically append observed_at column.
    """

    @declared_attr  # type: ignore
    def __tablename__(cls) -> str:
        """Generate tables names using all-lowercase snake_case."""
        return snake_case(cls.__name__)

    @classmethod
    def get_table_name(cls) -> str:
        """Return the SQLModel object's table name."""
        return str(cls.__tablename__)

    @classmethod
    def hash(cls, session, ignored: List[str] = ["observed_at"]) -> dict:
        pks = sorted([key.name for key in inspect(cls).primary_key])
        rows = session.exec(statement=select(cls))
        # no use of a generator as will need to serialize to JSON anyway
        hashes = {}
        for row in rows:
            # NOTE Pydantic is warning when read Gpu/Storage as dict
            # https://github.com/tiangolo/sqlmodel/issues/63#issuecomment-1081555082
            rowdict = row.model_dump(warnings=False)
            rowkeys = str(tuple(rowdict.get(pk) for pk in pks))
            for dropkey in [*ignored, *pks]:
                rowdict.pop(dropkey, None)
            rowhash = sha1(dumps(rowdict, sort_keys=True).encode()).hexdigest()
            hashes[rowkeys] = rowhash
        return hashes

    def __init__(self, *args, **kwargs):
        """Merge instace with the database if present.

        Checking if there's a parent vendor, and then try to sync the
        object using the parent's session private attribute.
        """
        super().__init__(*args, **kwargs)
        if hasattr(self, "vendor"):
            if hasattr(self.vendor, "_session"):
                self.vendor.merge_dependent(self)


class Json(BaseModel):
    """Custom base SQLModel class that supports dumping as JSON."""

    def __json__(self):
        return self.model_dump()


class Status(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Country(ScModel, table=True):
    """Country and continent mapping."""

    id: str = Field(
        default=None,
        primary_key=True,
        description="Country code by ISO 3166 alpha-2.",
    )
    continent: str = Field(description="Continent name.")

    vendors: List["Vendor"] = Relationship(back_populates="country")
    datacenters: List["Datacenter"] = Relationship(back_populates="country")


class VendorComplianceLink(ScModel, table=True):
    vendor_id: str = Field(foreign_key="vendor.id", primary_key=True)
    compliance_framework_id: str = Field(
        foreign_key="compliance_framework.id", primary_key=True
    )
    comment: Optional[str] = None

    vendor: "Vendor" = Relationship(back_populates="compliance_framework_links")
    compliance_framework: "ComplianceFramework" = Relationship(
        back_populates="vendor_links"
    )


class ComplianceFramework(ScModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    abbreviation: Optional[str]
    description: Optional[str]
    # TODO HttpUrl not supported by SQLModel
    # TODO upload to cdn.sparecores.com (s3/cloudfront)
    logo: Optional[str] = None
    # TODO HttpUrl not supported by SQLModel
    homepage: Optional[str] = None

    vendor_links: List[VendorComplianceLink] = Relationship(
        back_populates="compliance_framework"
    )


class Vendor(ScModel, table=True):
    """Compute resource vendors, such as cloud and server providers.

    Examples:
        >>> from sc_crawler.schemas import Vendor
        >>> from sc_crawler.lookup import countries
        >>> aws = Vendor(id='aws', name='Amazon Web Services', homepage='https://aws.amazon.com', country=countries["US"], founding_year=2002)
        >>> aws
        Vendor(id='aws'...
        >>> from sc_crawler import vendors
        >>> vendors.aws
        Vendor(id='aws'...
    """  # noqa: E501

    id: str = Field(primary_key=True)
    name: str
    # TODO HttpUrl not supported by SQLModel
    # TODO upload to cdn.sparecores.com
    logo: Optional[str] = None
    # TODO HttpUrl not supported by SQLModel
    homepage: str

    country_id: str = Field(foreign_key="country.id")
    state: Optional[str] = None
    city: Optional[str] = None
    address_line: Optional[str] = None
    zip_code: Optional[str] = None

    # https://dbpedia.org/ontology/Organisation
    founding_year: int

    compliance_framework_links: List[VendorComplianceLink] = Relationship(
        back_populates="vendor"
    )

    # TODO HttpUrl not supported by SQLModel
    status_page: Optional[str] = None

    status: Status = Status.ACTIVE

    # private attributes
    _methods: Optional[ImportString[ModuleType]] = PrivateAttr(default=None)
    _session: Optional[Session] = PrivateAttr()

    # relations
    country: Country = Relationship(back_populates="vendors")
    datacenters: List["Datacenter"] = Relationship(back_populates="vendor")
    zones: List["Zone"] = Relationship(back_populates="vendor")
    storages: List["Storage"] = Relationship(back_populates="vendor")
    traffics: List["Traffic"] = Relationship(back_populates="vendor")
    servers: List["Server"] = Relationship(back_populates="vendor")
    server_prices: List["ServerPrice"] = Relationship(back_populates="vendor")
    traffic_prices: List["TrafficPrice"] = Relationship(back_populates="vendor")
    ipv4_prices: List["Ipv4Price"] = Relationship(back_populates="vendor")
    storage_prices: List["StoragePrice"] = Relationship(back_populates="vendor")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # SQLModel does not validates pydantic typing,
        # only when writing to DB (much later in the process)
        if not self.id:
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
            "get_compliance_frameworks",
            "get_datacenters",
            "get_zones",
            "get_servers",
            "get_server_prices",
            "get_server_prices_spot",
            "get_storage_prices",
            "get_traffic_prices",
            "get_ipv4_prices",
        ]:
            if method not in methods:
                raise NotImplementedError(
                    f"Unsupported '{self.id}' vendor: missing '{method}' method."
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
                    [__name__.split(".", maxsplit=1)[0], "vendors", self.id]
                )
                self._methods = import_module(vendor_module)
            except Exception as exc:
                raise NotImplementedError(
                    f"Unsupported '{self.id}' vendor: no methods defined."
                ) from exc
        return self._methods

    @log_start_end
    def get_compliance_frameworks(self):
        """Get the vendor's all compliance frameworks."""
        self._get_methods().get_compliance_frameworks(self)

    @log_start_end
    def get_datacenters(self):
        """Get the vendor's all datacenters."""
        self._get_methods().get_datacenters(self)

    @log_start_end
    def get_zones(self):
        """Get all the zones in the vendor's datacenters."""
        self._get_methods().get_zones(self)

    @log_start_end
    def get_servers(self):
        """Get the vendor's all server types."""
        self._get_methods().get_servers(self)

    @log_start_end
    def get_server_prices(self):
        """Get the current standard/ondemand/reserved prices of all server types."""
        self._get_methods().get_server_prices(self)

    @log_start_end
    def get_server_prices_spot(self):
        """Get the current spot prices of all server types."""
        self._get_methods().get_server_prices_spot(self)

    @log_start_end
    def get_storage_prices(self):
        self._get_methods().get_storage_prices(self)

    @log_start_end
    def get_traffic_prices(self):
        self._get_methods().get_traffic_prices(self)

    @log_start_end
    def get_ipv4_prices(self):
        self._get_methods().get_ipv4_prices(self)

    def get_prices(self):
        self.get_server_prices()
        self.get_server_prices_spot()
        self.get_storage_prices()
        self.get_traffic_prices()
        self.get_ipv4_prices()

    def get_all(self):
        self.get_compliance_frameworks()
        self.get_datacenters()
        self.get_zones()
        self.get_servers()
        self.get_prices()

    def set_session(self, session):
        self._session = session

    def merge_dependent(self, obj):
        if self._session:
            self._session.merge(obj)


class Datacenter(ScModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    aliases: List[str] = Field(default=[], sa_column=Column(JSON))

    vendor_id: str = Field(foreign_key="vendor.id", primary_key=True)
    vendor: Vendor = Relationship(back_populates="datacenters")

    country_id: str = Field(foreign_key="country.id")
    state: Optional[str] = None
    city: Optional[str] = None
    address_line: Optional[str] = None
    zip_code: Optional[str] = None

    founding_year: Optional[int] = None
    green_energy: Optional[bool] = None

    status: Status = Status.ACTIVE

    # relations
    country: Country = Relationship(back_populates="datacenters")
    zones: List["Zone"] = Relationship(back_populates="datacenter")
    server_prices: List["ServerPrice"] = Relationship(back_populates="datacenter")
    traffic_prices: List["TrafficPrice"] = Relationship(back_populates="datacenter")
    ipv4_prices: List["Ipv4Price"] = Relationship(back_populates="datacenter")
    storage_prices: List["StoragePrice"] = Relationship(back_populates="datacenter")


class Zone(ScModel, table=True):
    id: str = Field(primary_key=True)
    datacenter_id: str = Field(foreign_key="datacenter.id", primary_key=True)
    vendor_id: str = Field(foreign_key="vendor.id", primary_key=True)
    name: str
    status: Status = Status.ACTIVE

    # relations
    datacenter: Datacenter = Relationship(back_populates="zones")
    vendor: Vendor = Relationship(back_populates="zones")
    server_prices: List["ServerPrice"] = Relationship(back_populates="zone")


class StorageType(str, Enum):
    HDD = "hdd"
    SSD = "ssd"
    NVME_SSD = "nvme ssd"
    NETWORK = "network"


class Storage(ScModel, table=True):
    id: str = Field(primary_key=True)
    vendor_id: str = Field(foreign_key="vendor.id", primary_key=True)
    name: str
    description: Optional[str]
    size: int = 0  # GiB
    storage_type: StorageType
    max_iops: Optional[int] = None
    max_throughput: Optional[int] = None  # MiB/s
    min_size: Optional[int] = None  # GiB
    max_size: Optional[int] = None  # GiB
    status: Status = Status.ACTIVE

    vendor: Vendor = Relationship(back_populates="storages")
    prices: List["StoragePrice"] = Relationship(back_populates="storage")


class TrafficDirection(str, Enum):
    IN = "inbound"
    OUT = "outbound"


class Traffic(ScModel, table=True):
    id: str = Field(primary_key=True)
    vendor_id: str = Field(foreign_key="vendor.id", primary_key=True)
    name: str
    description: Optional[str]
    direction: TrafficDirection
    status: Status = Status.ACTIVE

    vendor: Vendor = Relationship(back_populates="traffics")
    prices: List["TrafficPrice"] = Relationship(back_populates="traffic")


class Gpu(Json):
    manufacturer: str
    name: str
    memory: int  # MiB
    firmware: Optional[str] = None


class Disk(Json):
    size: int = 0  # GiB
    storage_type: StorageType


class CpuArchitecture(str, Enum):
    ARM64 = "arm64"
    ARM64_MAC = "arm64_mac"
    I386 = "i386"
    X86_64 = "x86_64"
    X86_64_MAC = "x86_64_mac"


class Server(ScModel, table=True):
    """Server types."""

    id: str = Field(
        primary_key=True,
        description="Server identifier, as called at the vendor.",
    )
    vendor_id: str = Field(
        foreign_key="vendor.id",
        primary_key=True,
        description="Vendor reference.",
    )
    name: str = Field(
        default=None,
        description="Human-friendly name or short description of the server.",
    )
    vcpus: int = Field(
        default=None,
        description="Default number of virtual CPUs (vCPU) of the server.",
    )
    # TODO join all below cpu fields into a Cpu object?
    cpu_cores: int = Field(
        default=None,
        description=(
            "Default number of CPU cores of the server. "
            "Equals to vCPUs when HyperThreading is disabled."
        ),
    )
    cpu_speed: Optional[float] = Field(
        default=None, description="CPU clock speed (GHz)."
    )
    cpu_architecture: CpuArchitecture = Field(
        default=None,
        description="CPU Architecture (arm64, arm64_mac, i386, or x86_64).",
    )
    cpu_manufacturer: Optional[str] = Field(
        default=None,
        description="The manufacturer of the processor.",
    )
    # TODO add the below extra fields
    # cpu_features:  # e.g. AVX; AVX2; AMD Turbo
    # cpu_allocation: dedicated | burstable | shared
    # cpu_name: str  # e.g. EPYC 7571
    memory: int = Field(
        default=None,
        description="RAM amount (MiB).",
    )
    gpu_count: int = Field(
        default=0,
        description="Number of GPU accelerator(s).",
    )
    # TODO sum and avg/each memory
    gpu_memory: Optional[int] = Field(
        default=None,
        description="Overall memory (MiB) available to all the GPU accelerator(s).",
    )
    gpu_name: Optional[str] = Field(
        default=None,
        description="The manufacturer and the name of the GPU accelerator(s).",
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
        description="Disk type (hdd, ssd, nvme ssd, or network).",
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
    ipv4: bool = Field(default=False, description="Complimentary IPv4 address.")

    billable_unit: str = Field(
        default=None,
        description="Time period for billing, e.g. hour or month.",
    )
    status: Status = Field(
        default=Status.ACTIVE,
        description="Status of the resource (active or inactive).",
    )

    vendor: Vendor = Relationship(back_populates="servers")
    prices: List["ServerPrice"] = Relationship(back_populates="server")


class Allocation(str, Enum):
    ONDEMAND = "ondemand"
    RESERVED = "reserved"
    SPOT = "spot"


class PriceUnit(str, Enum):
    YEAR = "year"
    MONTH = "month"
    HOUR = "hour"
    GIB = "GiB"
    GB = "GB"


class PriceTier(Json):
    lower: float
    upper: float
    price: float


# helper classes to inherit for most commonly used fields


class HasVendorPK(ScModel):
    vendor_id: str = Field(foreign_key="vendor.id", primary_key=True)


class HasDatacenterPK(ScModel):
    datacenter_id: str = Field(foreign_key="datacenter.id", primary_key=True)


class HasZonePK(ScModel):
    zone_id: str = Field(foreign_key="zone.id", primary_key=True)


class HasServer(ScModel):
    server_id: str = Field(foreign_key="server.id", primary_key=True)


class HasStorage(ScModel):
    storage_id: str = Field(foreign_key="storage.id", primary_key=True)


class HasTraffic(ScModel):
    traffic_id: str = Field(foreign_key="traffic.id", primary_key=True)


class HasPriceFields(ScModel):
    unit: PriceUnit
    # set to max price if tiered
    price: float
    # e.g. setup fee for dedicated servers,
    # or upfront costs of a reserved instance type
    price_upfront: float = 0
    price_tiered: List[PriceTier] = Field(default=[], sa_type=JSON)
    currency: str = "USD"


class ServerPriceExtraFields(ScModel):
    operating_system: str
    allocation: Allocation = Allocation.ONDEMAND


class ServerPriceBase(
    HasPriceFields,
    ServerPriceExtraFields,
    HasServer,
    HasZonePK,
    HasDatacenterPK,
    HasVendorPK,
):
    pass


class ServerPrice(ServerPriceBase, table=True):
    vendor: Vendor = Relationship(back_populates="server_prices")
    datacenter: Datacenter = Relationship(back_populates="server_prices")
    zone: Zone = Relationship(back_populates="server_prices")
    server: Server = Relationship(back_populates="prices")


class StoragePriceBase(HasPriceFields, HasStorage, HasDatacenterPK, HasVendorPK):
    pass


class StoragePrice(StoragePriceBase, table=True):
    vendor: Vendor = Relationship(back_populates="storage_prices")
    datacenter: Datacenter = Relationship(back_populates="storage_prices")
    storage: Storage = Relationship(back_populates="prices")


class TrafficPriceBase(HasPriceFields, HasTraffic, HasDatacenterPK, HasVendorPK):
    pass


class TrafficPrice(TrafficPriceBase, table=True):
    vendor: Vendor = Relationship(back_populates="traffic_prices")
    datacenter: Datacenter = Relationship(back_populates="traffic_prices")
    traffic: Traffic = Relationship(back_populates="prices")


class Ipv4PriceBase(HasPriceFields, HasDatacenterPK, HasVendorPK):
    pass


class Ipv4Price(Ipv4PriceBase, table=True):
    vendor: Vendor = Relationship(back_populates="ipv4_prices")
    datacenter: Datacenter = Relationship(back_populates="ipv4_prices")


VendorComplianceLink.model_rebuild()
Country.model_rebuild()
Vendor.model_rebuild()
Datacenter.model_rebuild()


def is_table(table):
    try:
        return table.model_config["table"] is True
    except Exception:
        return False


tables = [o for o in globals().values() if is_table(o)]
