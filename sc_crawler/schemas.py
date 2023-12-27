"""Schemas for vendors, datacenters, zones, and other resources."""


from .location import Location

from importlib import import_module
from types import ModuleType
from typing import List, Literal, Optional, ForwardRef
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
            vm = __name__.split('.')[0] + ".vendors." + self.identifier
            self._methods = import_module(vm)
        except Exception:
            raise NotImplementedError("Unsupported vendor")
            pass

    def get_instance_types(self):
        return self._methods.get_instance_types()

    def get_datacenters(self, identifiers: [str] = None):
        """Get datacenters of the vendor.

        Args:
            identifiers: datacenter ids to filter for
        """
        if not hasattr(self, '_datacenters'):
            self._datacenters = self._methods.get_datacenters(self)
        datacenters = self._datacenters
        if identifiers:
            datacenters = [datacenter for datacenter in datacenters
                           if datacenter.identifier in identifiers]
        return datacenters


class Datacenter(BaseModel):
    identifier: str
    name: str
    vendor: Vendor
    location: Location


class Zone(BaseModel):
    identifier: str
    name: str
    datacenter: Datacenter

    @computed_field
    @property
    def vendor(self) -> Vendor:
        return self.datacenter.vendor


class Resource(BaseModel):
    # vendor-specific resources (e.g. instance types) should be
    # prefixed with the vendor id, e.g. "aws:m5.xlarge"
    identifier: str
    name: str
    description: Optional[str]
    kind: Literal["compute", "traffic", "storage"]
    billable_unit: str  # e.g. GB, GiB, TB, runtime hours


class Server(Resource):
    kind: str = "compute"
    vcpus: int
    memory: int
    storage_size: int = 0  # GB
    storage_type: Optional[str]


class Storage(Resource):
    kind: str = "storage"
    max_iops: Optional[int]
    max_throughput: Optional[int]  # MiB/s
    min_size: Optional[int]  # GiB
    max_size: Optional[int]  # GiB
    billable_unit: str = "GiB"


class Traffic(Resource):
    kind: str = "traffic"
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


Vendor.update_forward_refs()
