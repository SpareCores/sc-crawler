import pytest
from pydantic import ValidationError
from sc_crawler import Vendor, Location


def test_bad_vendor_definition():
    with pytest.raises(ValidationError):
        Vendor()
        Vendor(identifier="foobar")
        Vendor(identifier="foobar", name="foobar")
        Vendor(identifier="foobar", name="foobar", homepage="https://foobar")
        Vendor(
            identifier="foobar",
            name="foobar",
            homepage="https://foobar",
            location=Location(country="US", city="Los Angeles"),
        )
    with pytest.raises(NotImplementedError):
        Vendor(
            identifier="foobar",
            name="foobar",
            homepage="https://foobar",
            location=Location(country="US", city="Los Angeles"),
            founding_year=2042,
        )


def test_aws():
    from sc_crawler import schemas, vendors

    assert isinstance(vendors.aws, schemas.Vendor)
    assert vendors.aws.founding_year == 2002
