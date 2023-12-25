"""Cloud compute resource vendors."""

from .location import Location

from typing import Optional
from pydantic import BaseModel, HttpUrl


class Vendor(BaseModel):
    """Base class for cloud compute resource vendors.

    Examples:
        >>> aws_loc = Location(country='US', city='Seattle', address_line1='410 Terry Ave N')
        >>> aws = Vendor(identifier='aws', name='Amazon Web Services', homepage='https://aws.amazon.com', location=aws_loc, found_date=2002)
    """  # noqa: E501

    identifier: str
    name: str
    logo: Optional[HttpUrl] = None  # TODO upload to cdn.sparecores.com
    homepage: HttpUrl
    location: Location
    found_date: int


    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        try:
            self.methods = __import__('providers.' + self.identifier)
        except:
            raise NotImplementedError('Unsupported vendor')
            pass

    def get_instance_types(self):
        return self.methods.get_instance_types()

