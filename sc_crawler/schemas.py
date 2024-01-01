"""Schemas for vendors, datacenters, zones, and other resources."""

from collections import ChainMap
from importlib import import_module
from types import ModuleType
from typing import Dict, List, Literal, Optional, ForwardRef
from pydantic import (
    BaseModel,
    HttpUrl,
    ImportString,
    PrivateAttr,
    computed_field,
)
from sqlmodel import Field, Relationship, Session, SQLModel, create_engine, JSON, Column


class Country(SQLModel, table=True):
    id: str = Field(default=None, primary_key=True)
    continent: str


class VendorComplianceLink(SQLModel, table=True):
    vendor: Optional[int] = Field(
        default=None, foreign_key="vendor.id", primary_key=True
    )
    compliance_framework: Optional[int] = Field(
        default=None, foreign_key="complianceframework.id", primary_key=True
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

    vendors: List["Vendor"] = Relationship(
        back_populates="compliance_frameworks", link_model=VendorComplianceLink
    )


class Vendor(SQLModel, table=True):
    """Base class for cloud compute resource vendors.

    Examples:
        >>> from sc_crawler import Location, Vendor, vendors
        >>> aws_loc = Location(country='US', city='Seattle', address_line1='410 Terry Ave N')
        >>> aws = Vendor(identifier='aws', name='Amazon Web Services', homepage='https://aws.amazon.com', location=aws_loc, founding_year=2002)
        >>> aws
        Vendor(identifier='aws'...
        >>> vendors.aws
        Vendor(identifier='aws'...
    """  # noqa: E501

    id: str = Field(default=None, primary_key=True)
    name: str
    # logo: Optional[HttpUrl] = None  # TODO upload to cdn.sparecores.com
    # homepage: HttpUrl
    country: str = Field(default=None, foreign_key="country.id")
    state: Optional[str] = None
    city: Optional[str] = None
    address_line: Optional[str] = None
    zip_code: Optional[str] = None

    # https://dbpedia.org/ontology/Organisation
    founding_year: int

    compliance_frameworks: List[ComplianceFramework] = Relationship(
        back_populates="vendors", link_model=VendorComplianceLink
    )

    # # private attributes
    # _methods: ImportString[ModuleType] = PrivateAttr()

    # relations
    datacenters: List["Datacenter"] = Relationship(back_populates="vendor")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        try:
            vendor_module = __name__.split(".")[0] + ".vendors." + self.id
            self._methods = import_module(vendor_module)
        except Exception as exc:
            raise NotImplementedError("Unsupported vendor") from exc

    def get_datacenters(self, session):
        """Get datacenters of the vendor."""
        return self._methods.get_datacenters(self)

    # def get_zones(self):
    #     """Get zones of the vendor from its datacenters."""
    #     # make sure datacenters filled in
    #     self._methods.get_datacenters(self)
    #     # unlist
    #     self._zones = dict(
    #         ChainMap(*[datacenter._zones for datacenter in self._datacenters])
    #     )

    # def get_instance_types(self):
    #     if not hasattr(self, "_servers"):
    #         self._servers = self._methods.get_instance_types(self)
    #     return self._servers

    # def get_all(self):
    #     self.get_datacenters()
    #     self.get_zones()
    #     self.get_instance_types()
    #     return


class Datacenter(SQLModel, table=True):
    id: str = Field(default=None, primary_key=True)
    vendor_id: str = Field(default=None, foreign_key="vendor.id", primary_key=True)
    name: str
    vendor: Vendor
    founding_year: Optional[int] = None
    green_energy: Optional[bool] = None

    vendor: Vendor = Relationship(back_populates="datacenters")

    country: str = Field(default=None, foreign_key="country.id")
    state: Optional[str] = None
    city: Optional[str] = None
    address_line: Optional[str] = None
    zip_code: Optional[str] = None
    @computed_field
    @property
    def zones(self) -> int:
        return len(self._zones)


# class Zone(BaseModel):
#     identifier: str
#     name: str
#     datacenter: Datacenter

#     @computed_field
#     @property
#     def vendor(self) -> Vendor:
#         return self.datacenter.vendor


# resource_types = Literal["compute", "traffic", "storage"]


# class Resource(BaseModel):
#     # vendor-specific resources (e.g. instance types) should be
#     # prefixed with the vendor id, e.g. "aws:m5.xlarge"
#     identifier: str
#     name: str
#     description: Optional[str]
#     resource_type: resource_types
#     billable_unit: str  # e.g. GB, GiB, TB, runtime hours


# storage_types = Literal["hdd", "ssd", "nvme ssd", "network"]


# class Storage(BaseModel):
#     size: int = 0  # GB
#     storage_type: storage_types


# class NetworkStorage(Resource, Storage):
#     resource_type: resource_types = "storage"
#     storage_type: storage_types = "network"
#     max_iops: Optional[int] = None
#     max_throughput: Optional[int] = None  # MiB/s
#     min_size: Optional[int] = None  # GiB
#     max_size: Optional[int] = None  # GiB
#     billable_unit: str = "GiB"


# class Gpu(BaseModel):
#     manufacturer: str
#     name: str
#     memory: int  # MiB
#     firmware: Optional[str] = None


# class Server(Resource):
#     resource_type: resource_types = "compute"
#     vcpus: int
#     cpu_cores: int
#     cpu_speed: Optional[float] = None  # Ghz
#     cpu_architecture: Literal["arm64", "arm64_mac", "i386", "x86_64"]
#     cpu_manufacturer: Optional[str] = None
#     memory: int
#     gpu_count: int = 0
#     gpu_memory: Optional[int] = None  # MiB
#     gpu_name: Optional[str] = None
#     gpus: List[Gpu] = []
#     storage_size: int = 0  # GB
#     storage_type: Optional[storage_types]
#     storages: List[Storage] = []
#     network_speed: Optional[float]  # Gbps


# class Traffic(Resource):
#     resource_type: resource_types = "traffic"
#     direction: Literal["inbound", "outbound"]
#     billable_unit: str = "GB"


# class Availability(BaseModel):
#     vendor: Vendor
#     # a resource might be available in all or only in one/few
#     # datacenters and zones e.g. incoming traffic is priced per
#     # datacenter, but sport instance price per zone
#     datacenter: Optional[Datacenter]
#     zone: Optional[Zone]
#     resource: Resource
#     allocation: Literal["ondemand", "spot"] = "ondemand"
#     price: float


Vendor.model_rebuild()
Datacenter.model_rebuild()
