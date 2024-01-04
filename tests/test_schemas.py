import pytest

from sc_crawler.schemas import Country, Vendor


def test_bad_vendor_definition():
    # TODO ValidationError once SQLModel supports pydantic typehint validation
    with pytest.raises(ValueError):
        Vendor()
        Vendor(id="foobar")
        Vendor(id="foobar", name="foobar")
        Vendor(id="foobar", name="foobar", homepage="https://foobar")
        Vendor(
            id="foobar",
            name="foobar",
            homepage="https://foobar",
            country=Country(id="US"),
        )
    with pytest.raises(NotImplementedError):
        Vendor(
            id="foobar",
            name="foobar",
            homepage="https://foobar",
            country=Country(id="US"),
            founding_year=2042,
        )


def test_aws():
    from sc_crawler import schemas, vendors

    assert isinstance(vendors.aws, schemas.Vendor)
    assert vendors.aws.founding_year == 2002
