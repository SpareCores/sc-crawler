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
    with (
        patch(
            "sc_crawler.vendors._upcloud._get_pg_service_type",
            return_value=payload,
        ),
        patch(
            "sc_crawler.vendors._upcloud._get_database_plans",
            return_value={"service_types": []},
        ),
    ):
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
    # 50 GiB / 150 GiB extra / 10 GiB step → decimal GB.
    assert by_id["2xCPU-4GB-50GB"]["storage_size"] == round(50 * _GIB_TO_GB)
    assert by_id["2xCPU-4GB-50GB"]["storage_extra_min"] == round(10 * _GIB_TO_GB)
    assert by_id["2xCPU-4GB-50GB"]["storage_extra_max"] == round(150 * _GIB_TO_GB)
    assert by_id["2xCPU-4GB-50GB"]["connection_pool"] is True
    assert by_id["2xCPU-4GB-50GB"]["sla"] == 99.999
    assert by_id["2xCPU-4GB-50GB"]["status"] == Status.ACTIVE
    assert by_id["4xCPU-16GB-200GB-ha"]["family"] == "2-node HA"
    assert by_id["4xCPU-16GB-200GB-ha"]["server_id"] == "4xCPU-16GB"
    # Cluster 200 GiB / 2 nodes = 100 GiB per node → decimal GB.
    assert by_id["4xCPU-16GB-200GB-ha"]["storage_size"] == round(100 * _GIB_TO_GB)
    assert by_id["4xCPU-16GB-200GB-ha"]["storage_extra_max"] == round(300 * _GIB_TO_GB)
    assert by_id["4xCPU-16GB-200GB-ha"]["ha"] == [DatabaseHaLevel.SINGLE_ZONE]
    assert by_id["4xCPU-16GB-200GB-ha"]["ha_strategy"] == [
        DatabaseHaStrategy.READABLE_CLUSTER
    ]
    assert by_id["4xCPU-16GB-200GB-ha"]["storage_extra_autosize"] is False
    assert by_id["4xCPU-16GB-200GB-ha"]["continuous_backups"] == 14


def test_upcloud_inventory_databases_maps_componentised_plans():
    vendor = Mock(vendor_id="upcloud")
    vendor.servers = [
        Mock(server_id="2xCPU-8GB"),
        Mock(server_id="HIMEM-64xCPU-512GB"),
        Mock(server_id="DEV-1xCPU-1GB"),
    ]
    with (
        patch(
            "sc_crawler.vendors._upcloud._get_pg_service_type",
            return_value={
                "properties": {
                    "version": {"enum": ["16", "17"]},
                    "pgbouncer": {"type": "object"},
                    "service_log": {"type": "boolean"},
                    "pg_stat_monitor_enable": {"type": "boolean"},
                },
                "service_plans": [],
            },
        ),
        patch(
            "sc_crawler.vendors._upcloud._get_database_plans",
            return_value={
                "service_types": [
                    {
                        "type": "pg",
                        "zones": ["fi-hel1"],
                        "compute_shapes": [
                            {
                                "compute": "rdb.development.1CPU-1GB",
                                "family": "development",
                                "cpu": 1,
                                "memory_gb": 1,
                                "dynamic_storage_supported": True,
                                "node_counts": [1],
                                "backups": ["mini"],
                                "storage": {
                                    "step_gib": 10,
                                    "options": [{"base_gib": 10, "max_gib": 40}],
                                },
                            },
                            {
                                "compute": "rdb.standard.2CPU-8GB",
                                "family": "standard",
                                "cpu": 2,
                                "memory_gb": 8,
                                "dynamic_storage_supported": True,
                                "node_counts": [1, 2, 3],
                                "backups": ["regular", "extended"],
                                "storage": {
                                    "step_gib": 10,
                                    "options": [
                                        {"base_gib": 80, "max_gib": 320},
                                        {"base_gib": 160, "max_gib": 640},
                                    ],
                                },
                            },
                            {
                                "compute": "rdb.memory.64CPU-512GB",
                                "family": "memory",
                                "cpu": 64,
                                "memory_gb": 512,
                                "dynamic_storage_supported": True,
                                "node_counts": [1, 2, 3],
                                "backups": ["regular"],
                                "storage": {
                                    "step_gib": 10,
                                    "options": [{"base_gib": 1000, "max_gib": 4000}],
                                },
                            },
                        ],
                    }
                ]
            },
        ),
    ):
        rows = inventory_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert by_id["rdb.development.1CPU-1GB"]["family"] == "Developer"
    assert by_id["rdb.development.1CPU-1GB"]["ha"] == [DatabaseHaLevel.NONE]
    assert by_id["rdb.development.1CPU-1GB"]["ha_strategy"] == [DatabaseHaStrategy.NONE]
    assert by_id["rdb.development.1CPU-1GB"]["server_id"] == "DEV-1xCPU-1GB"
    assert by_id["rdb.development.1CPU-1GB"]["continuous_backups"] == 3
    assert by_id["rdb.development.1CPU-1GB"]["max_read_replicas"] == 0
    assert by_id["rdb.standard.2CPU-8GB"]["family"] == "Standard"
    assert by_id["rdb.standard.2CPU-8GB"]["ha"] == [
        DatabaseHaLevel.SINGLE_ZONE,
        DatabaseHaLevel.NONE,
    ]
    assert by_id["rdb.standard.2CPU-8GB"]["ha_strategy"] == [
        DatabaseHaStrategy.READABLE_CLUSTER,
        DatabaseHaStrategy.PASSIVE_STANDBY,
        DatabaseHaStrategy.NONE,
    ]
    assert by_id["rdb.standard.2CPU-8GB"]["server_id"] == "2xCPU-8GB"
    assert by_id["rdb.standard.2CPU-8GB"]["storage_size"] is None
    assert by_id["rdb.standard.2CPU-8GB"]["storage_extra_min"] == round(80 * _GIB_TO_GB)
    assert by_id["rdb.standard.2CPU-8GB"]["storage_extra_max"] == round(
        640 * _GIB_TO_GB
    )
    assert by_id["rdb.standard.2CPU-8GB"]["continuous_backups"] == 15
    assert by_id["rdb.standard.2CPU-8GB"]["max_read_replicas"] == 2
    assert by_id["rdb.standard.2CPU-8GB"]["api_reference_object"] == {
        "service_type": "pg",
        "plan_compute": "rdb.standard.2CPU-8GB",
    }
    assert by_id["rdb.memory.64CPU-512GB"]["family"] == "High Memory"
    assert by_id["rdb.memory.64CPU-512GB"]["server_id"] == "HIMEM-64xCPU-512GB"
    assert by_id["rdb.memory.64CPU-512GB"]["memory_amount"] == 512 * 1024
    assert by_id["rdb.memory.64CPU-512GB"]["storage_size"] is None


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
    with (
        patch(
            "sc_crawler.vendors._upcloud._get_pg_service_type",
            return_value=payload,
        ),
        patch(
            "sc_crawler.vendors._upcloud._get_database_plans",
            return_value={"service_types": []},
        ),
    ):
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
        Mock(
            database_id="rdb.standard.2CPU-8GB",
            ha=[DatabaseHaLevel.SINGLE_ZONE, DatabaseHaLevel.NONE],
            ha_strategy=[
                DatabaseHaStrategy.READABLE_CLUSTER,
                DatabaseHaStrategy.PASSIVE_STANDBY,
                DatabaseHaStrategy.NONE,
            ],
        ),
        Mock(
            database_id="rdb.development.1CPU-1GB",
            ha=[DatabaseHaLevel.NONE],
            ha_strategy=[DatabaseHaStrategy.NONE],
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
                    "managed_database_compute_rdb.standard.2CPU-8GB": {
                        "price": 819.44,
                        "amount": 1,
                    },
                    "managed_database_compute_rdb.development.1CPU-1GB": {
                        "price": 125,
                        "amount": 1,
                    },
                    "managed_database_tiered_storage_standard": {"price": 1},
                }
            ],
        }
    }
    with patch("sc_crawler.vendors._upcloud._client", return_value=mock_client):
        prices = inventory_database_prices(vendor)
    by_key = {(p["database_id"], p["ha"], p["ha_strategy"]): p for p in prices}
    assert (
        by_key[("1x2xCPU-4GB-50GB", DatabaseHaLevel.NONE, DatabaseHaStrategy.NONE)][
            "allocation"
        ]
        == Allocation.ONDEMAND
    )
    assert (
        by_key[("1x2xCPU-4GB-50GB", DatabaseHaLevel.NONE, DatabaseHaStrategy.NONE)][
            "unit"
        ]
        == PriceUnit.HOUR
    )
    assert (
        by_key[("1x2xCPU-4GB-50GB", DatabaseHaLevel.NONE, DatabaseHaStrategy.NONE)][
            "price"
        ]
        == 5
    )
    assert (
        by_key[
            (
                "2x4xCPU-8GB-100GB",
                DatabaseHaLevel.SINGLE_ZONE,
                DatabaseHaStrategy.READABLE_CLUSTER,
            )
        ]["ha_strategy"]
        == DatabaseHaStrategy.READABLE_CLUSTER
    )
    # Per-node: 1x NONE, 1.9x 2-node standby, 2.6x 3-node readable.
    assert (
        by_key[
            ("rdb.standard.2CPU-8GB", DatabaseHaLevel.NONE, DatabaseHaStrategy.NONE)
        ]["price"]
        == 8.1944
    )
    assert (
        by_key[
            (
                "rdb.standard.2CPU-8GB",
                DatabaseHaLevel.SINGLE_ZONE,
                DatabaseHaStrategy.PASSIVE_STANDBY,
            )
        ]["price"]
        == 8.1944 * 1.9
    )
    assert (
        by_key[
            (
                "rdb.standard.2CPU-8GB",
                DatabaseHaLevel.SINGLE_ZONE,
                DatabaseHaStrategy.READABLE_CLUSTER,
            )
        ]["price"]
        == 8.1944 * 2.6
    )
    assert (
        by_key[
            ("rdb.development.1CPU-1GB", DatabaseHaLevel.NONE, DatabaseHaStrategy.NONE)
        ]["price"]
        == 1.25
    )
    assert (
        "rdb.development.1CPU-1GB",
        DatabaseHaLevel.SINGLE_ZONE,
        DatabaseHaStrategy.PASSIVE_STANDBY,
    ) not in by_key


def test_upcloud_inventory_database_storages_from_service_plans():
    vendor = Mock(vendor_id="upcloud")
    with (
        patch(
            "sc_crawler.vendors._upcloud._get_pg_service_type",
            return_value={
                "service_plans": [
                    {
                        "plan": "2xCPU-4GB-50GB",
                        "node_count": 1,
                        "storage_size": 51200,
                        "storage_step_size": 10240,
                        "storage_cap_size": 204800,
                    },
                    {
                        "plan": "4xCPU-16GB-200GB-ha",
                        "node_count": 2,
                        "storage_size": 204800,
                        "storage_step_size": 10240,
                        "storage_cap_size": 819200,
                    },
                ]
            },
        ),
        patch(
            "sc_crawler.vendors._upcloud._get_database_plans",
            return_value={
                "service_types": [
                    {
                        "type": "pg",
                        "compute_shapes": [
                            {
                                "compute": "rdb.standard.2CPU-8GB",
                                "storage": {
                                    "options": [
                                        {"base_gib": 80, "max_gib": 320},
                                        {"base_gib": 160, "max_gib": 640},
                                    ],
                                },
                            }
                        ],
                    }
                ]
            },
        ),
    ):
        rows = inventory_database_storages(vendor)
    by_id = {row["database_storage_id"]: row for row in rows}
    assert set(by_id) == {"tiered_storage_standard", "tiered_storage_maxiops"}
    assert by_id["tiered_storage_standard"]["scope"] == DatabaseStorageScope.DATA
    assert by_id["tiered_storage_standard"]["max_iops"] == 10000
    assert by_id["tiered_storage_maxiops"]["max_iops"] == 100000
    # Legacy per-node floor 50 GiB; componentised floor 80 GiB → min 50 GiB.
    assert by_id["tiered_storage_standard"]["min_size"] == round(50 * _GIB_TO_GB)
    # Componentised max 640 GiB beats legacy per-node cap 400 GiB.
    assert by_id["tiered_storage_maxiops"]["max_size"] == round(640 * _GIB_TO_GB)
    assert by_id["tiered_storage_maxiops"]["max_throughput"] is None


def test_upcloud_inventory_database_storage_prices_from_zone_list():
    vendor = Mock(vendor_id="upcloud")
    vendor.database_storages = [
        Mock(database_storage_id="tiered_storage_standard"),
        Mock(database_storage_id="tiered_storage_maxiops"),
    ]
    mock_client = Mock()
    mock_client.get_prices.return_value = {
        "prices": {
            "currency": "EUR",
            "zone": [
                {
                    "name": "fi-hel1",
                    "managed_database_tiered_storage_standard": {"price": 0.55},
                    "managed_database_tiered_storage_maxiops": {"price": 1.38},
                },
                {
                    "name": "de-fra1",
                    "managed_database_tiered_storage_standard": {"price": 0.55},
                    "managed_database_tiered_storage_maxiops": {"price": 1.38},
                },
            ],
        }
    }
    with patch("sc_crawler.vendors._upcloud._client", return_value=mock_client):
        rows = inventory_database_storage_prices(vendor)
    assert len(rows) == 4
    by_key = {(row["region_id"], row["database_storage_id"]): row for row in rows}
    assert set(by_key) == {
        ("fi-hel1", "tiered_storage_standard"),
        ("fi-hel1", "tiered_storage_maxiops"),
        ("de-fra1", "tiered_storage_standard"),
        ("de-fra1", "tiered_storage_maxiops"),
    }
    assert by_key[("fi-hel1", "tiered_storage_standard")]["unit"] == PriceUnit.GB_MONTH
    assert round(by_key[("fi-hel1", "tiered_storage_standard")]["price"], 4) == round(
        0.0055 * 730, 4
    )
    assert round(by_key[("fi-hel1", "tiered_storage_maxiops")]["price"], 4) == round(
        0.0138 * 730, 4
    )
