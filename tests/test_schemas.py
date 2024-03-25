import pytest
from sc_crawler.scd import scd_tables
from sc_crawler.schemas import Country, Vendor, tables


def test_scmodels_have_base():
    """Make sure each SQLModel has a Base Pydantic parent without relations."""
    for model in tables + scd_tables:
        assert hasattr(model, "__validator__")
        schema = model.__validator__
        assert schema.__name__.endswith("Base")
        assert hasattr(model, "__table__")
        assert not hasattr(schema, "__table__")


def test_bad_vendor_definition():
    # TODO ValidationError once SQLModel supports pydantic typehint validation
    with pytest.raises(ValueError):
        Vendor()
        Vendor(vendor_id="foobar")
        Vendor(vendor_id="foobar", name="foobar")
        Vendor(vendor_id="foobar", name="foobar", homepage="https://foobar")
        Vendor(
            vendor_id="foobar",
            name="foobar",
            homepage="https://foobar",
            country=Country(country_id="US"),
        )
    with pytest.raises(NotImplementedError):
        Vendor(
            vendor_id="foobar",
            name="foobar",
            homepage="https://foobar",
            country=Country(country_id="US"),
            founding_year=2042,
        )


def test_aws():
    from sc_crawler import schemas, vendors

    assert isinstance(vendors.aws, schemas.Vendor)
    assert vendors.aws.founding_year == 2002
