from sc_crawler.table_fields import DatabaseHaLevel, DatabaseHaStrategy, Status
from sc_crawler.vendor_helpers import server_status_from_availability_categories

_ALICLOUD_CATEGORY_TO_SERVER_STATUS = {
    "WithStock": Status.ACTIVE,
    "ClosedWithStock": Status.PLANNED_FOR_RETIREMENT,
    "WithoutStock": Status.INACTIVE,
    "ClosedWithoutStock": Status.RETIRED,
}


def test_status_best_picks_lifecycle_order():
    assert Status.best({Status.RETIRED, Status.ACTIVE}) == Status.ACTIVE
    assert (
        Status.best({Status.RETIRED, Status.PLANNED_FOR_RETIREMENT})
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert Status.best({Status.RETIRED, Status.INACTIVE}) == Status.INACTIVE
    assert Status.best({Status.RETIRED}) == Status.RETIRED


def test_status_is_orderable():
    assert Status.ACTIVE.is_orderable
    assert Status.PLANNED_FOR_RETIREMENT.is_orderable
    assert not Status.INACTIVE.is_orderable
    assert not Status.RETIRED.is_orderable


def test_alicloud_stock_categories_match_status_orderability():
    assert _ALICLOUD_CATEGORY_TO_SERVER_STATUS["WithStock"].is_orderable
    assert _ALICLOUD_CATEGORY_TO_SERVER_STATUS["ClosedWithStock"].is_orderable
    assert not _ALICLOUD_CATEGORY_TO_SERVER_STATUS["WithoutStock"].is_orderable
    assert not _ALICLOUD_CATEGORY_TO_SERVER_STATUS["ClosedWithoutStock"].is_orderable


def test_server_status_from_availability_categories_maps_each_value():
    assert (
        server_status_from_availability_categories(
            {"WithStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
        )
        == Status.ACTIVE
    )
    assert (
        server_status_from_availability_categories(
            {"ClosedWithStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
        )
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert (
        server_status_from_availability_categories(
            {"WithoutStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
        )
        == Status.INACTIVE
    )
    assert (
        server_status_from_availability_categories(
            {"ClosedWithoutStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
        )
        == Status.RETIRED
    )


def test_server_status_from_availability_categories_picks_best_across_zones():
    assert (
        server_status_from_availability_categories(
            {"ClosedWithoutStock", "WithStock", "WithoutStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
        )
        == Status.ACTIVE
    )
    assert (
        server_status_from_availability_categories(
            {"ClosedWithoutStock", "ClosedWithStock"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
        )
        == Status.PLANNED_FOR_RETIREMENT
    )


def test_server_status_from_availability_categories_missing_is_inactive():
    assert (
        server_status_from_availability_categories(
            set(),
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
        )
        == Status.INACTIVE
    )
    assert (
        server_status_from_availability_categories(
            {"UnknownCategory"},
            _ALICLOUD_CATEGORY_TO_SERVER_STATUS,
        )
        == Status.INACTIVE
    )


def test_database_ha_level_ordered():
    assert DatabaseHaLevel.ordered(
        {DatabaseHaLevel.NONE, DatabaseHaLevel.SINGLE_ZONE}
    ) == [DatabaseHaLevel.SINGLE_ZONE, DatabaseHaLevel.NONE]
    assert DatabaseHaLevel.ordered(
        {
            DatabaseHaLevel.NONE,
            DatabaseHaLevel.MULTI_REGION,
            DatabaseHaLevel.MULTI_ZONE,
            DatabaseHaLevel.SINGLE_ZONE,
        }
    ) == [
        DatabaseHaLevel.MULTI_REGION,
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.SINGLE_ZONE,
        DatabaseHaLevel.NONE,
    ]


def test_database_ha_strategy_ordered():
    assert DatabaseHaStrategy.ordered({DatabaseHaStrategy.NONE}) == [
        DatabaseHaStrategy.NONE
    ]
    assert DatabaseHaStrategy.ordered(
        {
            DatabaseHaStrategy.NONE,
            DatabaseHaStrategy.PASSIVE_STANDBY,
            DatabaseHaStrategy.READABLE_CLUSTER,
            DatabaseHaStrategy.MULTI_MASTER,
        }
    ) == [
        DatabaseHaStrategy.MULTI_MASTER,
        DatabaseHaStrategy.READABLE_CLUSTER,
        DatabaseHaStrategy.PASSIVE_STANDBY,
        DatabaseHaStrategy.NONE,
    ]
