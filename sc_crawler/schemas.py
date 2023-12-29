"""Schemas for vendors, datacenters, zones, and other resources."""


from .location import Location

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


class Vendor(BaseModel):
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

    identifier: str
    name: str
    logo: Optional[HttpUrl] = None  # TODO upload to cdn.sparecores.com
    homepage: HttpUrl
    location: Location

    # https://dbpedia.org/ontology/Organisation
    founding_year: int

    compliance_frameworks: List[ForwardRef("ComplianceFramework")] = []
    status_page: Optional[HttpUrl] = None

    @computed_field
    @property
    def datacenters(self) -> int:
        if hasattr(self, "_datacenters"):
            return len(self._datacenters)
        else:
            return 0

    @computed_field
    @property
    def zones(self) -> int:
        if hasattr(self, "_datacenters"):
            return sum([datacenter.zones for datacenter in self._datacenters])
        else:
            return 0

    # private attributes
    _methods: ImportString[ModuleType] = PrivateAttr()
    _datacenters: List[ForwardRef("Datacenter")] = PrivateAttr()
    _zones: List[ForwardRef("Zone")] = PrivateAttr()
    _servers: List[ForwardRef("Server")] = PrivateAttr()
    _storages: List[ForwardRef("Storage")] = PrivateAttr()
    _traffics: List[ForwardRef("Traffic")] = PrivateAttr()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        try:
            vm = __name__.split(".")[0] + ".vendors." + self.identifier
            self._methods = import_module(vm)
        except Exception:
            raise NotImplementedError("Unsupported vendor")

    def get_datacenters(self, identifiers: [str] = None):
        """Get datacenters of the vendor.

        Args:
            identifiers: datacenter ids to filter for
        """
        if not hasattr(self, "_datacenters"):
            self._datacenters = self._methods.get_datacenters(self)
        datacenters = self._datacenters
        if identifiers:
            datacenters = [
                datacenter
                for datacenter in datacenters
                if datacenter.identifier in identifiers
            ]
        return datacenters

    def get_zones(self):
        """Get zones of the vendor from its datacenters."""
        # make sure datacenters filled in
        self._methods.get_datacenters(self)
        # unlist
        self._zones = dict(
            ChainMap(*[datacenter._zones for datacenter in self._datacenters])
        )

    def get_instance_types(self):
        if not hasattr(self, "_servers"):
            self._servers = self._methods.get_instance_types(self)
        return self._servers

    def get_all(self):
        self.get_datacenters()
        self.get_zones()
        self.get_instance_types()
        return


class Datacenter(BaseModel):
    identifier: str
    name: str
    vendor: Vendor
    location: Location
    founding_year: Optional[int] = None
    green_energy: Optional[bool] = None

    _zones: Dict[str, ForwardRef("Zone")] = PrivateAttr()

    @computed_field
    @property
    def zones(self) -> int:
        return len(self._zones)


class Zone(BaseModel):
    identifier: str
    name: str
    datacenter: Datacenter

    @computed_field
    @property
    def vendor(self) -> Vendor:
        return self.datacenter.vendor


resource_types = Literal["compute", "traffic", "storage"]


class Resource(BaseModel):
    # vendor-specific resources (e.g. instance types) should be
    # prefixed with the vendor id, e.g. "aws:m5.xlarge"
    identifier: str
    name: str
    description: Optional[str]
    resource_type: resource_types
    billable_unit: str  # e.g. GB, GiB, TB, runtime hours


storage_types = Literal["hdd", "ssd", "nvme ssd", "network"]


class Storage(BaseModel):
    size: int = 0  # GB
    storage_type: storage_types


class NetworkStorage(Resource, Storage):
    resource_type: resource_types = "storage"
    storage_type: storage_types = "network"
    max_iops: Optional[int] = None
    max_throughput: Optional[int] = None  # MiB/s
    min_size: Optional[int] = None  # GiB
    max_size: Optional[int] = None  # GiB
    billable_unit: str = "GiB"


class Gpu(BaseModel):
    manufacturer: str
    name: str
    memory: int  # MiB
    firmware: Optional[str] = None


class Server(Resource):
    resource_type: resource_types = "compute"
    vcpus: int
    cores: int
    memory: int
    gpu_count: int = 0
    gpu_memory: Optional[int] = None  # MiB
    gpu_name: Optional[str] = None
    gpus: List[Gpu] = []
    storage_size: int = 0  # GB
    storage_type: Optional[storage_types]
    storages: List[Storage] = []
    network_speed: Optional[str]


class Traffic(Resource):
    resource_type: resource_types = "traffic"
    direction: Literal["inbound", "outbound"]
    billable_unit: str = "GB"


class Availability(BaseModel):
    vendor: Vendor
    # a resource might be available in all or only in one/few
    # datacenters and zones e.g. incoming traffic is priced per
    # datacenter, but sport instance price per zone
    datacenter: Optional[Datacenter]
    zone: Optional[Zone]
    resource: Resource
    allocation: Literal["ondemand", "spot"] = "ondemand"
    price: float


class ComplianceFramework(BaseModel):
    id: str
    name: str
    abbreviation: Optional[str]
    description: Optional[str]
    logo: Optional[HttpUrl] = None  # TODO upload to cdn.sparecores.com
    homepage: Optional[HttpUrl] = None


Vendor.model_rebuild()
Datacenter.model_rebuild()
