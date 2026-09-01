from unittest.mock import Mock, patch

from sc_crawler.table_fields import (
    Allocation,
    DatabaseEngine,
    DatabaseHaLevel,
    DatabaseHaStrategy,
    PriceUnit,
    Status,
)
from sc_crawler.vendors._vultr import (
    inventory_database_prices,
    inventory_database_storage_prices,
    inventory_database_storages,
    inventory_databases,
    inventory_servers,
)


def _plan(plan_id, locations):
    return {
        "id": plan_id,
        "type": "vc2",
        "vcpu_count": 1,
        "ram": 1024,
        "disk": 25,
        "disk_count": 1,
        "bandwidth": 1024,
        "cpu_model": "",
        "locations": locations,
    }


def test_vultr_inventory_servers_status_from_locations():
    vendor = Mock(vendor_id="vultr")
    with (
        patch(
            "sc_crawler.vendors._vultr._get_plans",
            return_value=[
                _plan("vc2-1c-1gb", ["ewr"]),
                _plan("vc2-1c-0.5gb-free", ["ewr"]),
                _plan("vc2-24c-97gb", []),
            ],
        ),
        patch("sc_crawler.vendors._vultr._get_plans_metal", return_value=[]),
    ):
        rows = inventory_servers(vendor)
    by_id = {row["server_id"]: row for row in rows}
    assert by_id["vc2-1c-1gb"]["status"] == Status.ACTIVE
    assert by_id["vc2-1c-0.5gb-free"]["status"] == Status.INACTIVE
    assert by_id["vc2-24c-97gb"]["status"] == Status.INACTIVE


def test_vultr_inventory_databases_maps_plans_and_versions():
    vendor = Mock(vendor_id="vultr")
    with (
        patch(
            "sc_crawler.vendors._vultr._get_database_plans",
            return_value=[
                {
                    "id": "vultr-dbaas-cc-2-80-4",
                    "type": "vdb",
                    "name": "Managed PostgreSQL 2vCPU",
                    "vcpu_count": 2,
                    "ram": 4096,
                    "disk": 80,
                    "number_of_nodes": 1,
                    "locations": ["ewr", "fra"],
                },
                {
                    "id": "vultr-dbaas-cc-4-160-8-ha",
                    "type": "vdb",
                    "name": "Managed PostgreSQL 4vCPU HA",
                    "vcpu_count": 4,
                    "ram": 8192,
                    "disk": 160,
                    "number_of_nodes": 2,
                    "locations": [],
                },
            ],
        ),
        patch(
            "sc_crawler.vendors._vultr._get_database_available_services",
            return_value={"available_services": {"pg": ["15", "16"]}},
        ),
    ):
        rows = inventory_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert by_id["vultr-dbaas-cc-2-80-4"]["engine"] == DatabaseEngine.POSTGRESQL
    assert by_id["vultr-dbaas-cc-2-80-4"]["engine_versions"] == ["15", "16"]
    assert by_id["vultr-dbaas-cc-2-80-4"]["family"] == "Cloud Compute"
    assert by_id["vultr-dbaas-cc-2-80-4"]["ha"] == [DatabaseHaLevel.NONE]
    assert by_id["vultr-dbaas-cc-2-80-4"]["status"] == Status.ACTIVE
    assert by_id["vultr-dbaas-cc-4-160-8-ha"]["ha"] == [DatabaseHaLevel.SINGLE_ZONE]
    assert by_id["vultr-dbaas-cc-4-160-8-ha"]["ha_strategy"] == [
        DatabaseHaStrategy.READABLE_CLUSTER
    ]
    assert by_id["vultr-dbaas-cc-4-160-8-ha"]["status"] == Status.INACTIVE


def test_vultr_inventory_database_prices_uses_hourly_with_monthly_tiers():
    vendor = Mock(vendor_id="vultr")
    vendor.databases = [
        Mock(database_id="vultr-dbaas-cc-2-80-4"),
        Mock(database_id="vultr-dbaas-cc-4-160-8-ha"),
    ]
    with patch(
        "sc_crawler.vendors._vultr._get_database_plans",
        return_value=[
            {
                "id": "vultr-dbaas-cc-2-80-4",
                "hourly_cost": 0.09,
                "monthly_cost": 60,
                "number_of_nodes": 1,
                "locations": ["ewr"],
                "currency": "USD",
            },
            {
                "id": "vultr-dbaas-cc-4-160-8-ha",
                "monthly_cost": 120,
                "number_of_nodes": 2,
                "locations": ["fra"],
                "currency": "USD",
            },
        ],
    ):
        rows = inventory_database_prices(vendor)
    by_id = {row["database_id"]: row for row in rows}
    single = by_id["vultr-dbaas-cc-2-80-4"]
    assert single["allocation"] == Allocation.ONDEMAND
    assert single["unit"] == PriceUnit.HOUR
    assert single["price"] == 0.09
    assert single["price_tiered"] == [
        {"lower": 0, "upper": 666, "price": 0.09},
        {"lower": 667, "upper": "Infinity", "price": 0},
    ]
    ha = by_id["vultr-dbaas-cc-4-160-8-ha"]
    assert ha["unit"] == PriceUnit.HOUR
    assert ha["price"] == 120 / 730
    assert ha["price_tiered"] == [
        {"lower": 0, "upper": 730, "price": 120 / 730},
        {"lower": 731, "upper": "Infinity", "price": 0},
    ]
    assert ha["ha"] == DatabaseHaLevel.SINGLE_ZONE


def test_vultr_inventory_database_storage_collectors_are_empty():
    vendor = Mock(vendor_id="vultr")
    assert inventory_database_storages(vendor) == []
    assert inventory_database_storage_prices(vendor) == []
