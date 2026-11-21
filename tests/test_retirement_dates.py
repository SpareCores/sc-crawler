from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sc_crawler.table_fields import Status
from sc_crawler.vendor_helpers import (
    retirement_date_from_rules,
    status_from_retirement_date,
)
from sc_crawler.vendors._alicloud import _ALICLOUD_RETIREMENT_RULES
from sc_crawler.vendors._aws import _AWS_EC2_RETIREMENT_RULES, _AWS_RDS_RETIREMENT_RULES
from sc_crawler.vendors._azure import _azure_sku_retirement_date
from sc_crawler.vendors._gcp import _gcp_machine_type_retirement_date
from sc_crawler.vendors._ovh import _database_end_of_sale


def test_status_from_retirement_date():
    assert status_from_retirement_date(None) == Status.ACTIVE
    retirement_date = date(2027, 1, 1)
    assert (
        status_from_retirement_date(retirement_date, as_of=date(2026, 12, 31))
        == Status.PLANNED_FOR_RETIREMENT
    )
    for as_of in (date(2027, 1, 1), date(2027, 1, 2)):
        assert status_from_retirement_date(retirement_date, as_of) == Status.RETIRED


@pytest.mark.parametrize(
    "rules, name, expected",
    [
        (_AWS_EC2_RETIREMENT_RULES, "u-9tb1.112xlarge", date(2025, 6, 20)),
        (_AWS_EC2_RETIREMENT_RULES, "u-24tb1.metal", date(2025, 6, 20)),
        (_AWS_EC2_RETIREMENT_RULES, "u-6tb1.112xlarge", None),
        (_AWS_EC2_RETIREMENT_RULES, "u7i-12tb.224xlarge", None),
        (_AWS_RDS_RETIREMENT_RULES, "db.m3.large", date(2023, 2, 1)),
        (_AWS_RDS_RETIREMENT_RULES, "db.r3.xlarge", date(2023, 2, 1)),
        (_AWS_RDS_RETIREMENT_RULES, "db.t2.micro", date(2024, 12, 31)),
        (_AWS_RDS_RETIREMENT_RULES, "db.m4.large", date(2024, 12, 31)),
        (_AWS_RDS_RETIREMENT_RULES, "db.m5.large", None),
        (_AWS_RDS_RETIREMENT_RULES, "db.r4g.large", None),
        (_ALICLOUD_RETIREMENT_RULES, "ecs.gn4.c4g1.xlarge", date(2026, 10, 1)),
        (_ALICLOUD_RETIREMENT_RULES, "ecs.sgn6i-vws.xlarge", date(2026, 10, 1)),
        (_ALICLOUD_RETIREMENT_RULES, "ecs.gn6i-c4g1.xlarge", None),
        (_ALICLOUD_RETIREMENT_RULES, "ecs.ebmc4.8xlarge", date(2026, 9, 15)),
        (_ALICLOUD_RETIREMENT_RULES, "ecs.ebmc4.16xlarge", None),
    ],
)
def test_retirement_date_from_rules(rules, name, expected):
    assert retirement_date_from_rules(name, rules) == expected


def test_azure_sku_retirement_date():
    api_dates = {"Standard_GS5": date(2028, 6, 1)}
    with patch(
        "sc_crawler.vendors._azure._vm_retirement_dates", return_value=api_dates
    ):
        # from the API, then from _AZURE_SKU_LIFECYCLE_RULES
        assert _azure_sku_retirement_date("Standard_GS5") == date(2028, 6, 1)
        assert _azure_sku_retirement_date("Standard_D2_v3") == date(2029, 11, 15)
        assert _azure_sku_retirement_date("Standard_D2s_v5") is None


def test_gcp_machine_type_retirement_date_prefers_deleted():
    def _deprecated(obsolete="", deleted=""):
        return SimpleNamespace(obsolete=obsolete, deleted=deleted)

    assert _gcp_machine_type_retirement_date(_deprecated()) is None
    assert _gcp_machine_type_retirement_date(
        _deprecated(obsolete="2027-01-01T00:00:00-08:00")
    ) == date(2027, 1, 1)
    assert _gcp_machine_type_retirement_date(
        _deprecated(
            obsolete="2027-01-01T00:00:00-08:00", deleted="2027-03-01T00:00:00Z"
        )
    ) == date(2027, 3, 1)


def test_ovh_database_end_of_sale_is_the_earliest_of_plan_and_flavor():
    assert _database_end_of_sale(None, {"status": "STABLE"}) is None
    assert _database_end_of_sale(
        {"endOfSale": "2027-05-12"}, {"endOfSale": None}
    ) == date(2027, 5, 12)
    assert _database_end_of_sale(
        {"endOfSale": "2027-05-12"}, {"endOfSale": "2027-01-31"}
    ) == date(2027, 1, 31)
