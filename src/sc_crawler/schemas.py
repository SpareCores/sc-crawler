"""Schemas for vendors, datacenters, zones, and other resources."""


from enum import Enum
from importlib import import_module
from types import ModuleType
from typing import List, Optional

from pydantic import (
    BaseModel,
    ImportString,
    PrivateAttr,
    model_validator,
)

# TODO SQLModel does NOT actually do pydantic validations
#      https://github.com/tiangolo/sqlmodel/issues/52
from sqlmodel import JSON, Column, Field, Relationship, SQLModel


class Json(BaseModel):
    """Custom base SQLModel class that supports dumping as JSON."""

    def __json__(self):
        return self.model_dump()


class Status(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Country(SQLModel, table=True):
    __table_args__ = {"comment": "Country and continent mapping."}
    id: str = Field(
        default=None,
        primary_key=True,
        sa_column_kwargs={"comment": "Country code by ISO 3166 alpha-2."},
    )
    continent: str = Field(sa_column_kwargs={"comment": "Continent name."})

    vendors: List["Vendor"] = Relationship(back_populates="country")
    datacenters: List["Datacenter"] = Relationship(back_populates="country")


class VendorComplianceLink(SQLModel, table=True):
    __tablename__: str = "vendor_compliance_link"  # type: ignore
    vendor_id: str = Field(foreign_key="vendor.id", primary_key=True)
    compliance_framework_id: str = Field(
        foreign_key="complianceframework.id", primary_key=True
    )
    comment: Optional[str] = None

    vendor: "Vendor" = Relationship(back_populates="compliance_framework_links")
    compliance_framework: "ComplianceFramework" = Relationship(
        back_populates="vendor_links"
    )


class ComplianceFramework(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    abbreviation: Optional[str]
    description: Optional[str]
    # TODO HttpUrl not supported by SQLModel
    # TODO upload to cdn.sparecores.com
    logo: Optional[str] = None
    # TODO HttpUrl not supported by SQLModel
    homepage: Optional[str] = None

    vendor_links: List[VendorComplianceLink] = Relationship(
        back_populates="compliance_framework"
    )


class Vendor(SQLModel, table=True):
    """Base class for cloud compute resource vendors.

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

    status: Status = "active"

    # private attributes
    _methods: ImportString[ModuleType] = PrivateAttr()

    # relations
    country: Country = Relationship(back_populates="vendors")
    datacenters: List["Datacenter"] = Relationship(back_populates="vendor")
    zones: List["Zone"] = Relationship(back_populates="vendor")
    addon_storages: List["AddonStorage"] = Relationship(back_populates="vendor")
    addon_traffics: List["AddonTraffic"] = Relationship(back_populates="vendor")
    servers: List["Server"] = Relationship(back_populates="vendor")
    prices: List["Price"] = Relationship(back_populates="vendor")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        try:
            # TODO SQLModel does not validates pydantic typing
            if not self.id:
                raise ValueError("No vendor id provided")
            if not self.name:
                raise ValueError("No vendor name provided")
            if not self.homepage:
                raise ValueError("No vendor homepage provided")
            if not self.country:
                raise ValueError("No vendor country provided")
            vendor_module = __name__.split(".")[0] + ".vendors." + self.id
            self._methods = import_module(vendor_module)
        except ValueError as exc:
            raise exc
        except Exception as exc:
            raise NotImplementedError("Unsupported vendor") from exc

    def get_datacenters(self):
        """Get datacenters of the vendor."""
        return self._methods.get_datacenters(self)

    def get_zones(self):
        """Get zones of the vendor from its datacenters."""
        return self._methods.get_zones(self)

    def get_instance_types(self):
        return self._methods.get_instance_types(self)

    def get_prices(self):
        return self._methods.get_prices(self)

    def get_all(self):
        self.get_datacenters()
        self.get_zones()
        self.get_instance_types()
        self.get_prices()
        return


class Datacenter(SQLModel, table=True):
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

    status: Status = "active"

    # relations
    country: Country = Relationship(back_populates="datacenters")
    zones: List["Zone"] = Relationship(back_populates="datacenter")
    prices: List["Price"] = Relationship(back_populates="datacenter")


class Zone(SQLModel, table=True):
    id: str = Field(primary_key=True)
    datacenter_id: str = Field(foreign_key="datacenter.id", primary_key=True)
    vendor_id: str = Field(foreign_key="vendor.id", primary_key=True)
    name: str
    status: Status = "active"

    # relations
    datacenter: Datacenter = Relationship(back_populates="zones")
    vendor: Vendor = Relationship(back_populates="zones")
    prices: List["Price"] = Relationship(back_populates="zone")


class StorageType(str, Enum):
    HDD = "hdd"
    SSD = "ssd"
    NVME_SSD = "nvme ssd"
    NETWORK = "network"


class AddonStorage(SQLModel, table=True):
    __tablename__: str = "addon_storage"  # type: ignore

    id: str = Field(primary_key=True)
    vendor_id: str = Field(foreign_key="vendor.id", primary_key=True)
    name: str
    description: Optional[str]
    size: int = 0
    storage_type: StorageType
    max_iops: Optional[int] = None
    max_throughput: Optional[int] = None  # MiB/s
    min_size: Optional[int] = None  # GiB
    max_size: Optional[int] = None  # GiB
    billable_unit: str = "GiB"
    status: Status = "active"

    vendor: Vendor = Relationship(back_populates="addon_storages")
    prices: List["Price"] = Relationship(back_populates="storage")


class TrafficDirection(str, Enum):
    IN = "inbound"
    OUT = "outbound"


class AddonTraffic(SQLModel, table=True):
    __tablename__: str = "addon_traffic"  # type: ignore

    id: str = Field(primary_key=True)
    vendor_id: str = Field(foreign_key="vendor.id", primary_key=True)
    name: str
    description: Optional[str]
    direction: TrafficDirection
    billable_unit: str = "GB"
    status: Status = "active"

    vendor: Vendor = Relationship(back_populates="addon_traffics")
    prices: List["Price"] = Relationship(back_populates="traffic")


class Gpu(Json):
    manufacturer: str
    name: str
    memory: int  # MiB
    firmware: Optional[str] = None


class Storage(Json):
    size: int = 0  # GiB
    storage_type: StorageType


class CpuArchitecture(str, Enum):
    ARM64 = "arm64"
    ARM64_MAC = "arm64_mac"
    I386 = "i386"
    X86_64 = "x86_64"
    X86_64_MAC = "x86_64_mac"


class Server(SQLModel, table=True):
    __table_args__ = {"comment": "Server types."}
    id: str = Field(
        primary_key=True,
        sa_column_kwargs={"comment": "Server identifier, as called at the vendor."},
    )
    vendor_id: str = Field(
        foreign_key="vendor.id",
        primary_key=True,
        sa_column_kwargs={"comment": "Vendor reference."},
    )
    name: str = Field(
        default=None,
        sa_column_kwargs={
            "comment": "Human-friendly name or short description of the server."
        },
    )
    vcpus: int = Field(
        default=None,
        sa_column_kwargs={
            "comment": "Default number of virtual CPUs (vCPU) of the server."
        },
    )
    # TODO join all below cpu fields into a Cpu object?
    cpu_cores: int = Field(
        default=None,
        sa_column_kwargs={
            "comment": (
                "Default number of CPU cores of the server. "
                "Equals to vCPUs when HyperThreading is disabled."
            )
        },
    )
    cpu_speed: Optional[float] = Field(
        default=None,
        sa_column_kwargs={"comment": "CPU clock speed (GHz)."},
    )
    cpu_architecture: CpuArchitecture = Field(
        default=None,
        sa_column_kwargs={
            "comment": "CPU Architecture (arm64, arm64_mac, i386, or x86_64)."
        },
    )
    cpu_manufacturer: Optional[str] = Field(
        default=None,
        sa_column_kwargs={"comment": "The manufacturer of the processor."},
    )
    # TODO add the below extra fields
    # cpu_features:  # e.g. AVX; AVX2; AMD Turbo
    # cpu_allocation: dedicated | burstable | shared
    # cpu_name: str  # e.g. EPYC 7571
    memory: int = Field(
        default=None,
        sa_column_kwargs={"comment": "RAM amount (MiB)."},
    )
    gpu_count: int = Field(
        default=0,
        sa_column_kwargs={"comment": "Number of GPU accelerator(s)."},
    )
    # TODO sum and avg/each memory
    gpu_memory: Optional[int] = Field(
        default=None,
        sa_column_kwargs={
            "comment": "Overall memory (MiB) available to all the GPU accelerator(s)."
        },
    )
    gpu_name: Optional[str] = Field(
        default=None,
        sa_column_kwargs={
            "comment": "The manufacturer and the name of the GPU accelerator(s)."
        },
    )
    gpus: List[Gpu] = Field(
        default=[],
        sa_column=Column(
            JSON,
            comment=(
                "JSON array of GPU accelerator details, including "
                "the manufacturer, name, and memory (MiB) of each GPU."
            ),
        ),
    )
    storage_size: int = Field(
        default=0,
        sa_column_kwargs={"comment": "Overall size (GB) of the disk(s)."},
    )
    storage_type: Optional[StorageType] = Field(
        default=None,
        sa_column_kwargs={"comment": "Disk type (hdd, ssd, nvme ssd, or network)."},
    )
    storages: List[Storage] = Field(
        default=[],
        sa_column=Column(
            JSON,
            comment=(
                "JSON array of disks attached to the server, including "
                "the size (MiB) and type of each disk."
            ),
        ),
    )
    network_speed: Optional[float] = Field(
        default=None,
        sa_column_kwargs={
            "comment": "The baseline network performance (Gbps) of the network card."
        },
    )

    billable_unit: str = Field(
        default=None,
        sa_column_kwargs={"comment": "Time period for billing, e.g. hour or month."},
    )
    status: Status = Field(
        default="active",
        sa_column_kwargs={"comment": "Status of the resource (active or inactive)."},
    )

    vendor: Vendor = Relationship(back_populates="servers")
    prices: List["Price"] = Relationship(back_populates="server")


class Allocation(str, Enum):
    ONDEMAND = "ondemand"
    RESERVED = "reserved"
    SPOT = "spot"


class PriceTier(Json):
    lower: float
    upper: float
    price: float


class Price(SQLModel, table=True):
    ## TODO add ipv4 pricing
    ## TODO created_at
    id: int = Field(primary_key=True)
    vendor_id: str = Field(foreign_key="vendor.id")
    # a resource might be available in all or only in one/few
    # datacenters and zones e.g. incoming traffic is priced per
    # datacenter, but sport instance price per zone
    datacenter_id: Optional[str] = Field(default=None, foreign_key="datacenter.id")
    zone_id: Optional[str] = Field(default=None, foreign_key="zone.id")
    server_id: Optional[str] = Field(default=None, foreign_key="server.id")
    traffic_id: Optional[str] = Field(default=None, foreign_key="addon_traffic.id")
    storage_id: Optional[str] = Field(default=None, foreign_key="addon_storage.id")
    allocation: Allocation = "ondemand"
    price: float  # max price if tiered
    # e.g. setup fee for dedicated servers, or upfront costs of a reserved instance type
    price_upfront: float = 0
    # TODO needs time interval as well and other complications .. maybe skip for now?
    price_tiered: List[PriceTier] = Field(default=[], sa_column=Column(JSON))
    currency: str = "USD"

    vendor: Vendor = Relationship(back_populates="prices")
    datacenter: Datacenter = Relationship(back_populates="prices")
    zone: Zone = Relationship(back_populates="prices")
    server: Server = Relationship(back_populates="prices")
    traffic: AddonTraffic = Relationship(back_populates="prices")
    storage: AddonStorage = Relationship(back_populates="prices")

    @model_validator(mode="after")
    def server_or_traffic_or_storage(self) -> "Price":
        if (self.server_id is None) + (self.traffic_id is None) + (
            self.storage_id is None
        ) != 2:
            raise ValueError("Exactly one Server, Traffic or Storage required.")
        return self


VendorComplianceLink.model_rebuild()
Country.model_rebuild()
Vendor.model_rebuild()
Datacenter.model_rebuild()
