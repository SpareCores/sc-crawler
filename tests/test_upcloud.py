from unittest.mock import Mock, patch

from sc_crawler.table_fields import (
    Allocation,
    DatabaseEngine,
    DatabaseHaLevel,
    DatabaseHaStrategy,
    DatabaseStorageScope,
    PriceUnit,
    Status,
)
from sc_crawler.utils import _GIB_TO_GB
from sc_crawler.vendors._upcloud import (
    _upcloud_server_status,
    inventory_database_prices,
    inventory_database_storage_prices,
    inventory_database_storages,
    inventory_databases,
)


def test_upcloud_server_status_from_current_offering():
    vendor = Mock(regions=[])
    assert (
        _upcloud_server_status(
            vendor,
            {
                "name": "HIMEM-2xCPU-16GB",
                "family": "general_purpose",
                "current_offering": "no",
            },
        )
        == Status.RETIRED
    )
    assert (
        _upcloud_server_status(
            vendor,
            {
                "name": "PREMIUM-2xCPU-4GB",
                "family": "premium",
                "current_offering": "yes",
            },
        )
        == Status.ACTIVE
    )


def test_upcloud_server_status_gpu_stock():
    vendor = Mock(regions=[Mock(region_id="de-fra1")])
    server = {
        "name": "GPU-8xCPU-64GB-1xL40S",
        "family": "gpu",
        "current_offering": "yes",
    }
    with patch(
        "sc_crawler.vendors._upcloud._get_gpu_region_availability",
        return_value={"GPU-8xCPU-64GB-1xL40S": {"amount": 2}},
    ):
        assert _upcloud_server_status(vendor, server) == Status.ACTIVE
    with patch(
        "sc_crawler.vendors._upcloud._get_gpu_region_availability",
        return_value={"GPU-8xCPU-64GB-1xL40S": {"amount": 0}},
    ):
        assert _upcloud_server_status(vendor, server) == Status.INACTIVE


def test_upcloud_server_status_gpu_without_regions_is_inactive():
    vendor = Mock(regions=[])
    assert (
        _upcloud_server_status(
            vendor,
            {
                "name": "GPU-8xCPU-64GB-1xL40S",
                "family": "gpu",
                "current_offering": "yes",
            },
        )
        == Status.INACTIVE
    )


def test_upcloud_inventory_databases_maps_pg_service_plans():
    vendor = Mock(vendor_id="upcloud")
    vendor.servers = [Mock(server_id="2xCPU-4GB"), Mock(server_id="4xCPU-16GB")]
    payload = {
        "properties": {
            "version": {"enum": ["16", "17"]},
            "pgbouncer": {"type": "object"},
            "pgaudit": {"type": "object"},
            "service_log": {"type": "boolean"},
            "pg_stat_monitor_enable": {"type": "boolean"},
            "ip_filter": {"type": "array"},
        },
        "service_plans": [
            {
                "plan": "2xCPU-4GB-50GB",
                "core_number": 2,
                "memory_amount": 4096,
                "storage_size": 51200,
                "storage_step_size": 10240,
                "storage_cap_size": 204800,
                "node_count": 1,
                "components": {
                    "compute": {"name": "2CPU-4GB", "cpu": 2, "memory_gb": 4},
                    "storage": {"included_gib": 50, "dynamic_storage_supported": True},
                },
                "backup_config_pg": {
                    "interval": 24,
                    "max_count": 7,
                    "recovery_mode": "pitr",
                },
                "zones": {"zone": [{"name": "fi-hel1"}]},
            },
            {
                "plan": "4xCPU-16GB-200GB-ha",
                "core_number": 4,
                "memory_amount": 16384,
                "storage_size": 204800,
                "storage_step_size": 10240,
                "storage_cap_size": 819200,
                "node_count": 2,
                "components": {
                    "compute": {"name": "4CPU-16GB", "cpu": 4, "memory_gb": 16},
                    "storage": {"included_gib": 200, "dynamic_storage_supported": True},
                },
                "backup_config_pg": {
                    "interval": 24,
                    "max_count": 14,
                    "recovery_mode": "pitr",
                },
                "zones": {"zone": [{"name": "fi-hel1"}]},
            },
        ],
    }
    mock_client = Mock()
    mock_client.api.get_request.return_value = payload
    with patch("sc_crawler.vendors._upcloud._client", return_value=mock_client):
        rows = inventory_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert by_id["2xCPU-4GB-50GB"]["engine"] == DatabaseEngine.POSTGRESQL
    assert by_id["2xCPU-4GB-50GB"]["family"] == "Single node"
    assert by_id["2xCPU-4GB-50GB"]["display_name"] == "2CPU-4GB"
    assert by_id["2xCPU-4GB-50GB"]["server_id"] == "2xCPU-4GB"
    assert by_id["2xCPU-4GB-50GB"]["ha"] == [DatabaseHaLevel.NONE]
    assert by_id["2xCPU-4GB-50GB"]["ha_strategy"] == [DatabaseHaStrategy.NONE]
    assert by_id["2xCPU-4GB-50GB"]["scheduled_backups"] is True
    assert by_id["2xCPU-4GB-50GB"]["continuous_backups"] == 7
    assert by_id["2xCPU-4GB-50GB"]["memory_amount"] == 4096
    assert by_id["2xCPU-4GB-50GB"]["storage_extra_min"] == round(
        10240 / 1024 * _GIB_TO_GB
    )
    assert by_id["2xCPU-4GB-50GB"]["storage_extra_max"] == round(
        (204800 - 51200) / 1024 * _GIB_TO_GB
    )
    assert by_id["2xCPU-4GB-50GB"]["connection_pool"] is True
    assert by_id["2xCPU-4GB-50GB"]["sla"] == 99.999
    assert by_id["2xCPU-4GB-50GB"]["status"] == Status.ACTIVE
    assert by_id["4xCPU-16GB-200GB-ha"]["family"] == "2-node HA"
    assert by_id["4xCPU-16GB-200GB-ha"]["server_id"] == "4xCPU-16GB"
    assert by_id["4xCPU-16GB-200GB-ha"]["ha"] == [DatabaseHaLevel.SINGLE_ZONE]
    assert by_id["4xCPU-16GB-200GB-ha"]["ha_strategy"] == [
        DatabaseHaStrategy.READABLE_CLUSTER
    ]
    assert by_id["4xCPU-16GB-200GB-ha"]["storage_extra_autosize"] is False
    assert by_id["4xCPU-16GB-200GB-ha"]["continuous_backups"] == 14


def test_upcloud_inventory_databases_keeps_server_id_none_when_no_match():
    vendor = Mock(vendor_id="upcloud")
    vendor.servers = [Mock(server_id="8xCPU-32GB")]
    payload = {
        "properties": {"version": {"enum": ["16"]}},
        "service_plans": [
            {
                "plan": "2xCPU-4GB-50GB",
                "core_number": 2,
                "memory_amount": 4096,
                "storage_size": 51200,
                "storage_step_size": 10240,
                "storage_cap_size": 204800,
                "node_count": 1,
                "components": {
                    "compute": {"name": "2CPU-4GB", "cpu": 2, "memory_gb": 4},
                    "storage": {"included_gib": 50, "dynamic_storage_supported": False},
                },
                "backup_config_pg": {
                    "interval": 24,
                    "max_count": 7,
                    "recovery_mode": "pitr",
                },
                "zones": {"zone": [{"name": "fi-hel1"}]},
            }
        ],
    }
    mock_client = Mock()
    mock_client.api.get_request.return_value = payload
    with patch("sc_crawler.vendors._upcloud._client", return_value=mock_client):
        rows = inventory_databases(vendor)
    assert rows[0]["server_id"] is None
    assert rows[0]["storage_extra_min"] == 0
    assert rows[0]["storage_extra_max"] == 0
    assert rows[0]["storage_extra_autosize"] is False


def test_upcloud_inventory_database_prices_from_price_list():
    vendor = Mock(vendor_id="upcloud")
    vendor.databases = [
        Mock(
            database_id="1x2xCPU-4GB-50GB",
            ha=[DatabaseHaLevel.NONE],
            ha_strategy=[DatabaseHaStrategy.NONE],
        ),
        Mock(
            database_id="2x4xCPU-8GB-100GB",
            ha=[DatabaseHaLevel.SINGLE_ZONE],
            ha_strategy=[DatabaseHaStrategy.READABLE_CLUSTER],
        ),
    ]
    mock_client = Mock()
    mock_client.get_prices.return_value = {
        "prices": {
            "currency": "EUR",
            "zone": [
                {
                    "name": "fi-hel1",
                    "managed_database_1x2xCPU-4GB-50GB": {"price": 500, "amount": 1},
                    "managed_database_2x4xCPU-8GB-100GB": {
                        "price": 1800,
                        "amount": 1,
                    },
                }
            ],
        }
    }
    with patch("sc_crawler.vendors._upcloud._client", return_value=mock_client):
        prices = inventory_database_prices(vendor)
    by_key = {(p["database_id"], p["ha"]): p for p in prices}
    assert (
        by_key[("1x2xCPU-4GB-50GB", DatabaseHaLevel.NONE)]["allocation"]
        == Allocation.ONDEMAND
    )
    assert by_key[("1x2xCPU-4GB-50GB", DatabaseHaLevel.NONE)]["unit"] == PriceUnit.HOUR
    assert by_key[("1x2xCPU-4GB-50GB", DatabaseHaLevel.NONE)]["price"] == 5
    assert (
        by_key[("2x4xCPU-8GB-100GB", DatabaseHaLevel.SINGLE_ZONE)]["ha_strategy"]
        == DatabaseHaStrategy.READABLE_CLUSTER
    )


def test_upcloud_inventory_database_storages_from_service_plans():
    vendor = Mock(vendor_id="upcloud")
    payload = {
        "service_plans": [
            {
                "plan": "2xCPU-4GB-50GB",
                "storage_size": 51200,
                "storage_step_size": 10240,
                "storage_cap_size": 204800,
            },
            {
                "plan": "4xCPU-16GB-200GB-ha",
                "storage_size": 204800,
                "storage_step_size": 10240,
                "storage_cap_size": 819200,
            },
        ]
    }
    mock_client = Mock()
    mock_client.api.get_request.return_value = payload
    with patch("sc_crawler.vendors._upcloud._client", return_value=mock_client):
        rows = inventory_database_storages(vendor)
    assert len(rows) == 1
    row = rows[0]
    assert row["database_storage_id"] == "additional-disk"
    assert row["scope"] == DatabaseStorageScope.DATA
    assert row["min_size"] == 0
    assert row["max_size"] == round((819200 - 204800) / 1024 * _GIB_TO_GB)
    assert row["max_iops"] == 100000
    assert row["max_throughput"] is None


def test_upcloud_inventory_database_storage_prices_from_zone_list():
    vendor = Mock(vendor_id="upcloud")
    vendor.database_storages = [Mock(database_storage_id="additional-disk")]
    mock_client = Mock()
    mock_client.get_prices.return_value = {
        "prices": {
            "currency": "EUR",
            "zone": [
                {
                    "name": "fi-hel1",
                    "managed_database_tiered_storage_standard": {"price": 1},
                },
                {
                    "name": "de-fra1",
                    "managed_database_tiered_storage_standard": {"price": 1},
                },
            ],
        }
    }
    with patch("sc_crawler.vendors._upcloud._client", return_value=mock_client):
        rows = inventory_database_storage_prices(vendor)
    assert len(rows) == 2
    assert {row["region_id"] for row in rows} == {"fi-hel1", "de-fra1"}
    assert rows[0]["database_storage_id"] == "additional-disk"
    assert rows[0]["unit"] == PriceUnit.GB_MONTH
    assert round(rows[0]["price"], 4) == 7.3
