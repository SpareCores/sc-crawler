from sqlmodel import Session, SQLModel, create_engine, select

from sc_crawler.table_fields import (
    DatabaseHaLevel,
    DatabaseHaStrategy,
    Disk,
    Status,
    StorageType,
)
from sc_crawler.tables import Country, Region
from sc_crawler.vendor_helpers import (
    disk_speed_totals,
    server_status_from_availability_categories,
    split_disk_speed,
)
from sc_crawler.vendors import vendors

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
    assert Status.best({Status.ARCHIVED, Status.RETIRED}) == Status.RETIRED


def test_status_is_orderable():
    assert Status.ACTIVE.is_orderable
    assert Status.PLANNED_FOR_RETIREMENT.is_orderable
    assert not Status.INACTIVE.is_orderable
    assert not Status.RETIRED.is_orderable
    assert not Status.ARCHIVED.is_orderable


def test_status_archived_is_general():
    assert Status.ARCHIVED.is_general
    assert not Status.RETIRED.is_general


def test_set_table_rows_inactive_keeps_archived():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Country(country_id="DE", continent="Europe"))
        vendor = session.merge(vendors.hcloud.model_copy())
        for region_id, status in [("2", Status.ARCHIVED), ("nbg1", Status.ACTIVE)]:
            session.add(
                Region(
                    vendor_id="hcloud",
                    region_id=region_id,
                    name=region_id,
                    api_reference=region_id,
                    display_name=region_id,
                    country_id="DE",
                    green_energy=True,
                    status=status,
                )
            )
        session.commit()
        vendor.session = session
        vendor.set_table_rows_inactive(Region)
        statuses = dict(session.exec(select(Region.region_id, Region.status)).all())
    assert statuses == {"2": Status.ARCHIVED, "nbg1": Status.INACTIVE}


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


def test_azure_gpu_memory_is_gib():
    from sc_crawler.vendors._azure import _gpu_spec

    assert _gpu_spec("Standard_ND96isr_H100_v5", "8") == (8, "H100", 80 * 1024)


def test_disk_speed_totals_sums_known_values():
    disks = [
        Disk(size=10, storage_type=StorageType.SSD, read_iops_max=100),
        Disk(
            size=10,
            storage_type=StorageType.NVME_SSD,
            read_iops_max=50,
            write_iops_max=20,
        ),
        Disk(size=10, storage_type=StorageType.SSD),
    ]
    assert disk_speed_totals(disks) == {
        "storage_read_iops_max": 150,
        "storage_write_iops_max": 20,
        "storage_read_throughput_max": None,
        "storage_write_throughput_max": None,
    }
    assert disk_speed_totals([]) == dict.fromkeys(
        [
            "storage_read_iops_max",
            "storage_write_iops_max",
            "storage_read_throughput_max",
            "storage_write_throughput_max",
        ]
    )


def test_split_disk_speed():
    assert split_disk_speed(1_000, 4) == 250
    assert split_disk_speed(1_000, 3) == 333
    assert split_disk_speed(None, 4) is None
    assert split_disk_speed(0, 4) is None
    assert split_disk_speed(1_000, 0) is None


def test_disk_speed_fields_default_to_none_for_old_rows():
    # rows stored before the speed fields existed
    disk = Disk.model_validate({"size": 10, "storage_type": "ssd"})
    assert (
        disk.read_iops_max,
        disk.write_iops_max,
        disk.read_throughput_max,
        disk.write_throughput_max,
    ) == (None, None, None, None)
