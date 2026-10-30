from unittest.mock import Mock, patch

import pytest

from sc_crawler.table_fields import (
    Allocation,
    DatabaseEngine,
    DatabaseHaLevel,
    DatabaseHaStrategy,
    PriceUnit,
    Status,
)
from sc_crawler.vendors._vultr import (
    _database_family,
    _database_series,
    _server_family,
    _server_series,
    _warn_unknown,
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


def _metal_plan(plan_id, locations):
    return {
        "id": plan_id,
        "type": "SSD",
        "cpu_count": 6,
        "cpu_threads": 12,
        "cpu_manufacturer": "Intel",
        "cpu_model": "E-2286G",
        "cpu_mhz": 4000,
        "ram": 32768,
        "disk": 960,
        "disk_count": 2,
        "bandwidth": 5120,
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
        patch(
            "sc_crawler.vendors._vultr._get_plans_metal",
            return_value=[_metal_plan("vbm-6c-32gb", ["ewr"])],
        ),
    ):
        rows = inventory_servers(vendor)
    by_id = {row["server_id"]: row for row in rows}
    assert by_id["vc2-1c-1gb"]["status"] == Status.ACTIVE
    assert by_id["vc2-1c-1gb"]["api_reference_object"] == {"plan": "vc2-1c-1gb"}
    assert by_id["vc2-1c-0.5gb-free"]["status"] == Status.INACTIVE
    assert by_id["vc2-24c-97gb"]["status"] == Status.INACTIVE
    expected_storage_ids = [
        "block_storage_high_perf",
        "block_storage_storage_opt",
    ]
    assert by_id["vc2-1c-1gb"]["compatible_storage_ids"] == expected_storage_ids
    assert by_id["vbm-6c-32gb"]["compatible_storage_ids"] == []


def test_vultr_inventory_databases_maps_plans_and_versions():
    vendor = Mock(vendor_id="vultr")
    with (
        patch(
            "sc_crawler.vendors._vultr._get_database_plans",
            return_value=[
                {
                    "id": "vultr-dbaas-business-cc-2-80-4",
                    "type": "vdb",
                    "name": "Managed PostgreSQL 2vCPU",
                    "vcpu_count": 2,
                    "ram": 4096,
                    "disk": 80,
                    "number_of_nodes": 1,
                    "locations": ["ewr", "fra"],
                },
                {
                    "id": "vultr-dbaas-business-cc-4-160-8-ha",
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
    assert (
        by_id["vultr-dbaas-business-cc-2-80-4"]["engine"] == DatabaseEngine.POSTGRESQL
    )
    assert by_id["vultr-dbaas-business-cc-2-80-4"]["engine_versions"] == ["15", "16"]
    assert by_id["vultr-dbaas-business-cc-2-80-4"]["family"] == "Business"
    # the series is the hardware, the description keeps the tier and hardware text
    assert by_id["vultr-dbaas-business-cc-2-80-4"]["series"] == "vc2"
    assert (
        "Business Cloud Compute"
        in by_id["vultr-dbaas-business-cc-2-80-4"]["description"]
    )
    assert by_id["vultr-dbaas-business-cc-2-80-4"]["ha"] == [DatabaseHaLevel.NONE]
    assert by_id["vultr-dbaas-business-cc-2-80-4"]["status"] == Status.ACTIVE
    assert by_id["vultr-dbaas-business-cc-4-160-8-ha"]["ha"] == [
        DatabaseHaLevel.SINGLE_ZONE
    ]
    assert by_id["vultr-dbaas-business-cc-4-160-8-ha"]["ha_strategy"] == [
        DatabaseHaStrategy.READABLE_CLUSTER
    ]
    assert by_id["vultr-dbaas-business-cc-4-160-8-ha"]["status"] == Status.INACTIVE


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


@pytest.mark.parametrize(
    "plan_type,plan_id,family,series",
    [
        # ids from the live public /v2/plans and /v2/plans-metal responses
        ("vc2", "vc2-1c-0.5gb", "Cloud Compute", "vc2"),
        ("vhf", "vhf-2c-2gb", "High Frequency Compute", "vhf"),
        ("vhp", "vhp-2c-4gb-amd", "High Performance", "vhp-amd"),
        ("vhp", "vhp-1c-1gb-intel", "High Performance", "vhp-intel"),
        ("voc", "voc-g-1c-4gb-30s-amd", "Optimized Cloud Compute", "voc-g"),
        ("voc", "voc-m-1c-8gb-50s-amd", "Optimized Cloud Compute", "voc-m"),
        ("vx1", "vx1-m-2c-16g", "VX1 Cloud Compute", "vx1-m"),
        ("vcg", "vcg-l40s-16c-180g-48vram", "Cloud GPU", "l40s"),
        ("vdm", "vcg-a100-12c-120g-80vram", "Dedicated Metal GPU", "a100"),
        ("SSD", "vbm-4c-32gb", "Bare Metal SSD", None),
        ("NVMe", "vbm-24c-384gb-amd", "Bare Metal NVMe", None),
        ("NVMe", "vbm-112c-2048gb-8-h100-gpu", "Bare Metal NVMe", "h100"),
        ("NVMe", "vbm-72c-480gb-gh200-gpu", "Bare Metal NVMe", "gh200"),
    ],
)
def test_vultr_server_family_and_series(plan_type, plan_id, family, series):
    server = {"id": plan_id, "type": plan_type}
    assert _server_family(server) == family
    assert _server_series(server) == series


def test_vultr_unknown_plan_type_is_empty_and_warned_once():
    _warn_unknown.cache_clear()
    new = {"id": "vzz-2c-4gb", "type": "vzz"}
    with patch("sc_crawler.vendors._vultr.logger") as logger:
        assert _server_family(new) is None
        assert _server_family(new) is None
        assert _server_series(new) is None
        assert _server_series(new) is None
        # known values do not warn
        assert _server_family({"id": "vc2-1c-1gb", "type": "vc2"}) == "Cloud Compute"
    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert len(warnings) == 2
    assert "family of vzz" in warnings[0]
    assert "series of vzz-2c-4gb" in warnings[1]


@pytest.mark.parametrize(
    "plan_id,plan_type,family,series",
    [
        ("vultr-dbaas-hobbyist-cc-1-25-1", "vdb", "Hobbyist", "vc2"),
        ("vultr-dbaas-startup-cc-hp-amd-1-64-2", "cc_hp_amd", "Startup", "vhp-amd"),
        (
            "vultr-dbaas-business-cc-hp-intel-2-128-4",
            "cc_hp_intel",
            "Business",
            "vhp-intel",
        ),
        ("vultr-dbaas-premium-occ-gp-1-30-4", "occ_gp", "Premium", "voc-g"),
        ("vultr-dbaas-premium-occ-so-1-150-8", "occ_so", "Premium", "voc-s"),
    ],
)
def test_vultr_database_family_is_tier_and_series_is_hardware(
    plan_id, plan_type, family, series
):
    plan = {"id": plan_id, "type": plan_type}
    assert _database_family(plan) == family
    assert _database_series(plan) == series


def test_vultr_unknown_database_tier_and_type_are_empty_and_warned():
    _warn_unknown.cache_clear()
    plan = {"id": "vultr-dbaas-enterprise-zz-1-1-1", "type": "zz"}
    with patch("sc_crawler.vendors._vultr.logger") as logger:
        assert _database_family(plan) is None
        assert _database_series(plan) is None
    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert len(warnings) == 2
