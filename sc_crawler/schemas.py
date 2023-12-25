"""Schemas for vendors, datacenters, zones, and other resources."""


from .location import Location

from importlib import import_module
from types import ModuleType
from typing import Optional
from pydantic import BaseModel, HttpUrl, ImportString, PrivateAttr


class Vendor(BaseModel):
    """Base class for cloud compute resource vendors.

    Examples:
        >>> from sc_crawler import Location, Vendor
        >>> aws_loc = Location(country='US', city='Seattle', address_line1='410 Terry Ave N')
        >>> aws = Vendor(identifier='aws', name='Amazon Web Services', homepage='https://aws.amazon.com', location=aws_loc, found_date=2002)
    """  # noqa: E501

    identifier: str
    name: str
    logo: Optional[HttpUrl] = None  # TODO upload to cdn.sparecores.com
    homepage: HttpUrl
    location: Location
    found_date: int
    _methods: ImportString[ModuleType] = PrivateAttr()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        try:
            vm = 'sc_crawler.vendors.' + self.identifier
            self._methods = import_module(vm)
        except Exception:
            raise NotImplementedError('Unsupported vendor')
            pass

    def get_instance_types(self):
        return self._methods.get_instance_types()
