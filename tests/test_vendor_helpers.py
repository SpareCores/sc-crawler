from sc_crawler.table_fields import Status
from sc_crawler.vendor_helpers import (
    server_price_status_from_availability_category,
    server_status_from_availability_categories,
)

_ALICLOUD_CATEGORY_TO_SERVER_STATUS = {
    "WithStock": Status.ACTIVE,
    "ClosedWithStock": Status.PLANNED_FOR_RETIREMENT,
    "WithoutStock": Status.INACTIVE,
    "ClosedWithoutStock": Status.RETIRED,
}
_ALICLOUD_SERVER_STATUS_PRIORITY = (
    Status.ACTIVE,
    Status.PLANNED_FOR_RETIREMENT,
    Status.INACTIVE,
    Status.RETIRED,
)
_ALICLOUD_ORDERABLE = frozenset({"WithStock", "ClosedWithStock"})


def test_server_status_from_availability_categories_maps_each_value():
    assert (
        server_status_from_availability_categories(
            {"WithStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
            _ALICLOUD_SERVER_STATUS_PRIORITY,
        )
        == Status.ACTIVE
    )
    assert (
        server_status_from_availability_categories(
            {"ClosedWithStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
            _ALICLOUD_SERVER_STATUS_PRIORITY,
        )
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert (
        server_status_from_availability_categories(
            {"WithoutStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
            _ALICLOUD_SERVER_STATUS_PRIORITY,
        )
        == Status.INACTIVE
    )
    assert (
        server_status_from_availability_categories(
            {"ClosedWithoutStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
            _ALICLOUD_SERVER_STATUS_PRIORITY,
        )
        == Status.RETIRED
    )


def test_server_status_from_availability_categories_picks_best_across_zones():
    assert (
        server_status_from_availability_categories(
            {"ClosedWithoutStock", "WithStock", "WithoutStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
            _ALICLOUD_SERVER_STATUS_PRIORITY,
        )
        == Status.ACTIVE
    )
    assert (
        server_status_from_availability_categories(
            {"ClosedWithoutStock", "ClosedWithStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
            _ALICLOUD_SERVER_STATUS_PRIORITY,
        )
        == Status.PLANNED_FOR_RETIREMENT
    )


def test_server_status_from_availability_categories_missing_is_retired():
    assert (
        server_status_from_availability_categories(
            set(),
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
            _ALICLOUD_SERVER_STATUS_PRIORITY,
        )
        == Status.RETIRED
    )


def test_server_price_status_from_availability_category():
    assert (
        server_price_status_from_availability_category("WithStock", _ALICLOUD_ORDERABLE)
        == Status.ACTIVE
    )
    assert (
        server_price_status_from_availability_category(
            "ClosedWithStock", _ALICLOUD_ORDERABLE
        )
        == Status.ACTIVE
    )
    assert (
        server_price_status_from_availability_category(
            "WithoutStock", _ALICLOUD_ORDERABLE
        )
        == Status.INACTIVE
    )
    assert (
        server_price_status_from_availability_category(
            "ClosedWithoutStock", _ALICLOUD_ORDERABLE
        )
        == Status.INACTIVE
    )
    assert (
        server_price_status_from_availability_category(None, _ALICLOUD_ORDERABLE)
        == Status.INACTIVE
    )
