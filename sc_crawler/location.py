"""Helpers to work with physical addresses."""

from pydantic import BaseModel, computed_field, field_validator
from pydantic_extra_types.country import CountryAlpha2
from typing import Optional

# country codes: https://en.wikipedia.org/wiki/ISO_3166-1#Codes
# mapping: https://github.com/manumanoj0010/countrydetails/blob/master/Countrydetails/data/continents.json  # noqa: E501
country_continent_mapping = {
    "FI": "Europe",
    "FR": "Europe",
    "DE": "Europe",
    "NL": "Europe",
    "GB": "Europe",
    "US": "North America",
    "ZA": "Africa",
}


class Location(BaseModel):
    """Structured physical address reference including continent, country etc.

    Examples:
        >>> l=Location(country='GB', city='London', address_line1='221B Baker Street', zip_code='NW1 6XE')
        >>> l
        Location(country='GB', state=None, city='London', address_line1='221B Baker Street', address_line2=None, zip_code='NW1 6XE', continent='Europe')
        >>> print(l)
        221B Baker Street
        London NW1 6XE
        United Kingdom
    """  # noqa: E501

    country: CountryAlpha2
    state: Optional[str] = None
    city: str
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    zip_code: Optional[str] = None

    @field_validator("country")
    @classmethod
    def country_code_known(cls, country: str) -> str:
        if country not in country_continent_mapping.keys():
            raise LookupError("Unknown country")
        return country

    @computed_field
    @property
    def continent(self) -> str:
        return country_continent_mapping.get(self.country)

    def __str__(self):
        address = self.address_line1
        if self.address_line2:
            address += " " + self.address_line2
        address += "\n" + self.city
        if self.state:
            address += " " + self.state
        if self.zip_code:
            address += " " + self.zip_code
        address += "\n" + self.country.short_name
        return address
