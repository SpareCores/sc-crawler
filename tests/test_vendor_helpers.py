from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select, update

from sc_crawler.table_fields import (
    CpuAllocation,
    CpuArchitecture,
    DatabaseHaLevel,
    DatabaseHaStrategy,
    Disk,
    Status,
    StorageType,
)
from sc_crawler.tables import Country, Database, Region, Server
from sc_crawler.vendor_helpers import (
    _warn_missing_retirement_date,
    checked_retirement_date,
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


def test_set_table_rows_inactive_keeps_retiring_and_retired():
    # these statuses are only valid for servers and databases, but the filter is
    # generic, so it is checked on the minimal Region rows
    statuses = {
        "fsn1": Status.PLANNED_FOR_RETIREMENT,
        "hel1": Status.RETIRED,
        "nbg1": Status.ACTIVE,
    }
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Country(country_id="DE", continent="Europe"))
        vendor = session.merge(vendors.hcloud.model_copy())
        for region_id in statuses:
            session.add(
                Region(
                    vendor_id="hcloud",
                    region_id=region_id,
                    name=region_id,
                    api_reference=region_id,
                    display_name=region_id,
                    country_id="DE",
                    green_energy=True,
                )
            )
        session.commit()
        for region_id, status in statuses.items():
            session.exec(
                update(Region)
                .where(Region.region_id == region_id)
                .values(status=status)
            )
        vendor.session = session
        vendor.set_table_rows_inactive(Region)
        result = dict(session.exec(select(Region.region_id, Region.status)).all())
    assert result == statuses | {"nbg1": Status.INACTIVE}


def _retiring_rows(model, today):
    """Rows by id: (status, retirement date) covering kept and changed cases."""
    return {
        "planned-past": (Status.PLANNED_FOR_RETIREMENT, today - timedelta(days=1)),
        "planned-today": (Status.PLANNED_FOR_RETIREMENT, today),
        "planned-future": (Status.PLANNED_FOR_RETIREMENT, today + timedelta(days=1)),
        "planned-no-date": (Status.PLANNED_FOR_RETIREMENT, None),
        "retired": (Status.RETIRED, today - timedelta(days=30)),
        "active": (Status.ACTIVE, None),
    }


def _add_row(session, model, row_id, status, retirement_date):
    common = dict(
        vendor_id="hcloud",
        name=row_id,
        api_reference=row_id,
        display_name=row_id,
        description=row_id,
        status=status,
        retirement_date=retirement_date,
    )
    if model is Server:
        session.add(
            Server(
                server_id=row_id,
                vcpus=1,
                memory_amount=1024,
                cpu_allocation=CpuAllocation.SHARED,
                cpu_architecture=CpuArchitecture.X86_64,
                **common,
            )
        )
    else:
        session.add(Database(database_id=row_id, **common))


@pytest.mark.parametrize("model", [Server, Database])
def test_set_table_rows_inactive_retires_kept_planned_rows_past_their_date(model):
    today = datetime.now(UTC).date()
    rows = _retiring_rows(model, today)
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        vendor = session.merge(vendors.hcloud.model_copy())
        for row_id, (status, retirement_date) in rows.items():
            _add_row(session, model, row_id, status, retirement_date)
        session.commit()
        vendor.session = session
        vendor.set_table_rows_inactive(model)
        id_column = model.server_id if model is Server else model.database_id
        result = {
            row_id: (status, retirement_date)
            for row_id, status, retirement_date in session.exec(
                select(id_column, model.status, model.retirement_date)
            ).all()
        }
    assert result == {
        # the vendor no longer updates them: retired from the date (inclusive)
        "planned-past": (Status.RETIRED, today - timedelta(days=1)),
        "planned-today": (Status.RETIRED, today),
        # kept as is
        "planned-future": rows["planned-future"],
        # announced for retirement, then gone: retired, date stays empty
        "planned-no-date": (Status.RETIRED, None),
        "retired": rows["retired"],
        # not returned by the vendor any more
        "active": (Status.INACTIVE, None),
    }


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


def test_checked_retirement_date_warns_once_for_retiring_skus_without_date():
    _warn_missing_retirement_date.cache_clear()
    with patch("sc_crawler.vendor_helpers.logger") as logger:
        # retiring without date: empty, warned once per SKU
        for _ in range(2):
            assert (
                checked_retirement_date("aws", "m1.small", Status.RETIRED, None) is None
            )
        assert (
            checked_retirement_date(
                "aws", "m1.medium", Status.PLANNED_FOR_RETIREMENT, None
            )
            is None
        )
        # date known, or not retiring: no warning
        assert checked_retirement_date(
            "aws", "m1.large", Status.RETIRED, date(2025, 1, 1)
        ) == date(2025, 1, 1)
        assert checked_retirement_date("aws", "m5.large", Status.ACTIVE, None) is None
        assert (
            checked_retirement_date("aws", "m5.xlarge", Status.INACTIVE, None) is None
        )
    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert len(warnings) == 2
    assert "m1.small" in warnings[0] and "m1.medium" in warnings[1]


def test_set_table_rows_inactive_keeps_oci_planned_rows_with_past_dates():
    # OCI previous generation shapes: past end of orderability, still running
    today = datetime.now(UTC).date()
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        vendor = session.merge(vendors.oci.model_copy())
        session.add(
            Server(
                vendor_id="oci",
                server_id="VM.Standard2.1",
                name="VM.Standard2.1",
                api_reference="VM.Standard2.1",
                display_name="VM.Standard2.1",
                description="VM.Standard2.1",
                vcpus=2,
                memory_amount=15 * 1024,
                cpu_allocation=CpuAllocation.DEDICATED,
                cpu_architecture=CpuArchitecture.X86_64,
                status=Status.PLANNED_FOR_RETIREMENT,
                retirement_date=today - timedelta(days=365),
            )
        )
        session.commit()
        vendor.session = session
        vendor.set_table_rows_inactive(Server)
        status = session.exec(select(Server.status)).one()
    assert status == Status.PLANNED_FOR_RETIREMENT
