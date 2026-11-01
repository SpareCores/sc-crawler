from unittest.mock import Mock, patch

import pytest

from sc_crawler.table_fields import (
    AcceleratorType,
    Allocation,
    DatabaseEngine,
    DatabaseHaLevel,
    DatabaseHaStrategy,
    DatabaseSecurityFeature,
    DatabaseWireProtocol,
    PriceUnit,
    Status,
)
from sc_crawler.vendors._aws import (
    _active_region_ids,
    _boto_describe_db_major_engine_versions_first,
    _compatible_storage_ids,
    _database_compatible_storage_ids,
    _database_family,
    _describe_orderable_db_instance_options_for_class_with_progress,
    _extract_rds_bundled_storage_size,
    _get_rds_instance_products_by_region,
    _get_server_products,
    _get_storage_bounds_from_orderable_options,
    _instance_family,
    _instance_series,
    _server_series_categories,
    _warn_unknown_family,
)
from sc_crawler.vendors._aws import (
    _reconcile_server_status as aws_reconcile_server_status,
)
from sc_crawler.vendors._aws import (
    inventory_database_prices as aws_database_prices,
)
from sc_crawler.vendors._aws import (
    inventory_database_storage_prices as aws_database_storage_prices,
)
from sc_crawler.vendors._aws import (
    inventory_database_storages as aws_database_storages,
)
from sc_crawler.vendors._aws import (
    inventory_databases as aws_databases,
)
from sc_crawler.vendors._aws import (
    inventory_server_prices as aws_server_prices,
)


def _aws_ondemand_terms(price: str = "0.1", currency: str = "USD") -> dict:
    return {
        "OnDemand": {
            "term": {
                "priceDimensions": {
                    "dim": {"pricePerUnit": {currency: price}},
                }
            }
        }
    }


def _aws_rds_instance_product(
    *,
    instance_type: str,
    region: str = "us-east-1",
    deployment: str = "Single-AZ",
    family: str = "General purpose",
    vcpu: str = "2",
    memory: str = "8 GiB",
    storage: str = "EBS Only",
    price: str = "0.145",
) -> dict:
    return {
        "product": {
            "productFamily": "Database Instance",
            "attributes": {
                "instanceType": instance_type,
                "regionCode": region,
                "deploymentOption": deployment,
                "instanceFamily": family,
                "vcpu": vcpu,
                "memory": memory,
                "storage": storage,
            },
        },
        "terms": _aws_ondemand_terms(price),
    }


def _aws_rds_storage_product(
    *,
    volume_type: str,
    region: str = "us-east-1",
    deployment: str = "Single-AZ",
    price: str = "0.115",
) -> dict:
    return {
        "product": {
            "productFamily": "Database Storage",
            "attributes": {
                "volumeType": volume_type,
                "regionCode": region,
                "deploymentOption": deployment,
            },
        },
        "terms": _aws_ondemand_terms(price),
    }


def _aws_vendor(*, regions=None, servers=None, databases=None, database_storages=None):
    vendor = Mock(vendor_id="aws")
    vendor.regions = regions or []
    vendor.servers = servers or []
    vendor.databases = databases or []
    vendor.database_storages = database_storages or []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    return vendor


# instance categories as returned by the Pricing API (sample of the real mapping)
_API_CATEGORIES = {
    "m5": "General Purpose",
    "m8gd": "General Purpose",
    "t1": "General Purpose",
    "t4g": "General Purpose",
    "c7i-flex": "Compute Optimized",
    "r8g": "Memory Optimized",
    "u-12tb1": "Memory Optimized",
    "i4i": "Storage Optimized",
    "p5": "Accelerated Computing",
    "p6-b200": "Accelerated Computing",
    "trn2": "Accelerated Computing",
    "f1": "Accelerated Computing",
    "g3s": "Accelerated Computing",
    "p2": "Accelerated Computing",
    "hpc7a": "High-Performance Computing",
}


@pytest.fixture(autouse=True)
def _no_pricing_api_categories():
    """Keep the tests offline: instance categories from a fake Pricing API."""
    with patch(
        "sc_crawler.vendors._aws._server_series_categories",
        return_value=_API_CATEGORIES,
    ):
        yield


def test_aws_extract_rds_storage_size():
    assert _extract_rds_bundled_storage_size(None) is None
    assert _extract_rds_bundled_storage_size("EBS Only") is None
    assert _extract_rds_bundled_storage_size("ebs only") is None
    assert _extract_rds_bundled_storage_size("2 x 1425 NVMe SSD") == 3060
    assert _extract_rds_bundled_storage_size("3 X 950 NVMe SSD") == 3060
    assert _extract_rds_bundled_storage_size("not a size") is None


def test_aws_orderable_options_skips_failing_region_when_sentry_captures():
    from contextlib import contextmanager, suppress

    vendor = _aws_vendor()
    options = [{"DBInstanceClass": "db.m5.large", "MultiAZCapable": True}]

    def describe(region, db_instance_class):
        if region == "ap-southeast-7":
            raise ConnectionError(f"rds.{region}.amazonaws.com refused")
        if region == "us-east-1":
            return options
        return []

    @contextmanager
    def capture(vendor, on_error=None):
        with suppress(ConnectionError):
            yield

    with (
        patch(
            "sc_crawler.vendors._aws._boto_describe_orderable_db_instance_options",
            side_effect=describe,
        ),
        patch(
            "sc_crawler.vendors._aws.sentry_capture_or_raise",
            side_effect=capture,
        ),
    ):
        result = _describe_orderable_db_instance_options_for_class_with_progress(
            ["ap-southeast-7", "us-east-1"],
            "db.m5.large",
            vendor,
        )
    assert result == options
    vendor.progress_tracker.advance_task.assert_called_once()


def test_aws_active_region_ids_priority_and_active_only():
    vendor = _aws_vendor(
        regions=[
            Mock(region_id="ap-south-1", status=Status.ACTIVE),
            Mock(region_id="eu-west-1", status=Status.ACTIVE),
            Mock(region_id="us-east-1", status=Status.INACTIVE),
            Mock(region_id="eu-central-1", status=Status.ACTIVE),
            Mock(region_id="us-west-2", status=Status.ACTIVE),
        ]
    )
    assert _active_region_ids(vendor) == [
        "eu-west-1",
        "eu-central-1",
        "ap-south-1",
        "us-west-2",
    ]


def test_aws_major_engine_versions_try_regions_in_order():
    with patch(
        "sc_crawler.vendors._aws._boto_describe_db_major_engine_versions",
        side_effect=[[], ["15", "16"], ["14"]],
    ) as describe:
        versions = _boto_describe_db_major_engine_versions_first(
            ["eu-west-1", "us-east-1", "eu-central-1"]
        )
    assert versions == ["15", "16"]
    assert describe.call_args_list[0].args == ("eu-west-1",)
    assert describe.call_args_list[1].args == ("us-east-1",)
    assert describe.call_count == 2


def test_aws_instance_products_by_region_collects_all_deployment_options():
    products = [
        _aws_rds_instance_product(
            instance_type="db.m5.large",
            region="us-east-1",
            deployment="Multi-AZ",
            price="0.29",
            vcpu="99",  # should be overwritten by later Single-AZ attrs
        ),
        _aws_rds_instance_product(instance_type="db.m5.large", region="us-east-1"),
        _aws_rds_instance_product(
            instance_type="db.c6gd.large",
            region="us-east-1",
            deployment="Multi-AZ (readable standbys)",
            price="0.50",
            family="Compute optimized",
        ),
        _aws_rds_instance_product(instance_type="db.r6g.large", region="eu-west-1"),
        {
            "product": {
                "productFamily": "Database Storage",
                "attributes": {"volumeType": "Magnetic", "regionCode": "us-east-1"},
            },
            "terms": _aws_ondemand_terms(),
        },
    ]
    with patch(
        "sc_crawler.vendors._aws._boto_get_rds_products",
        return_value=products,
    ):
        by_region, deployment_options = (
            _get_rds_instance_products_by_region.__wrapped__()
        )
    assert set(by_region) == {"us-east-1", "eu-west-1"}
    assert set(by_region["us-east-1"]) == {"db.m5.large", "db.c6gd.large"}
    # Prefer Single-AZ attrs when both Multi-AZ and Single-AZ meters exist.
    assert by_region["us-east-1"]["db.m5.large"]["vcpu"] == "2"
    assert by_region["us-east-1"]["db.m5.large"]["deploymentOption"] == "Single-AZ"
    # Readable-standbys-only classes still enter the catalog index.
    assert (
        by_region["us-east-1"]["db.c6gd.large"]["deploymentOption"]
        == "Multi-AZ (readable standbys)"
    )
    assert by_region["eu-west-1"]["db.r6g.large"]["vcpu"] == "2"
    assert deployment_options["db.m5.large"] == frozenset({"Single-AZ", "Multi-AZ"})
    assert deployment_options["db.c6gd.large"] == frozenset(
        {"Multi-AZ (readable standbys)"}
    )
    assert deployment_options["db.r6g.large"] == frozenset({"Single-AZ"})


def test_aws_storage_bounds_from_orderable_options():
    options_by_database = {
        "db.m5.large": [
            {
                "StorageType": "gp3",
                "MinStorageSize": 20,
                "MaxStorageSize": 65536,
                "MaxIopsPerDbInstance": 40000,
                "MaxStorageThroughputPerDbInstance": 4000,
            },
            {
                "StorageType": "gp2",
                "MinStorageSize": 20,
                "MaxStorageSize": 65536,
                "MaxIopsPerDbInstance": 16000,
                "MaxStorageThroughputPerDbInstance": 250,
            },
        ],
        "db.t3.micro": [
            {
                "StorageType": "gp3",
                "MinStorageSize": 5,
                "MaxStorageSize": 16384,
                "MaxIopsPerDbInstance": 64000,
                "MaxStorageThroughputPerDbInstance": 1000,
            },
        ],
    }
    bounds = _get_storage_bounds_from_orderable_options(options_by_database)
    assert bounds["gp3"]["min_size"] == 5
    assert bounds["gp3"]["max_size"] == 70369
    assert bounds["gp3"]["max_iops"] == 64000
    assert bounds["gp3"]["max_throughput"] == 4000
    assert bounds["gp2"]["max_iops"] == 16000
    assert bounds["gp2"]["max_size"] == 70369
    assert "standard" not in bounds


def test_aws_inventory_databases_description_server_id_and_capabilities():
    vendor = _aws_vendor(
        regions=[Mock(region_id="us-east-1", status=Status.ACTIVE)],
        servers=[
            Mock(server_id="m5.large", api_reference="m5.large"),
            Mock(server_id="r6gd.xlarge", api_reference="r6gd.xlarge"),
        ],
    )
    prices_by_region = {
        "us-east-1": {
            "db.m5.large": {
                "instanceFamily": "General purpose",
                "vcpu": "2",
                "memory": "8 GiB",
                "storage": "EBS Only",
            },
            "db.r6gd.xlarge": {
                "instanceFamily": "Memory optimized",
                "vcpu": "4",
                "memory": "32 GiB",
                "storage": "1 x 118 NVMe SSD",
            },
        }
    }
    options_by_database = {
        "db.m5.large": [
            {
                "StorageType": "gp3",
                "MultiAZCapable": True,
                "SupportsStorageAutoscaling": True,
                "MinStorageSize": 20,
                "MaxStorageSize": 65536,
                "SupportsStorageEncryption": True,
                "SupportsEnhancedMonitoring": True,
                "SupportsPerformanceInsights": True,
                "ReadReplicaCapable": True,
            },
        ],
        "db.r6gd.xlarge": [
            {
                "MultiAZCapable": False,
                "SupportsStorageAutoscaling": False,
                "MinStorageSize": 100,
                "MaxStorageSize": 16384,
                "SupportsStorageEncryption": True,
                "SupportsEnhancedMonitoring": False,
                "SupportsPerformanceInsights": False,
                "ReadReplicaCapable": False,
            },
        ],
    }
    with (
        patch(
            "sc_crawler.vendors._aws._get_rds_instance_products_by_region",
            return_value=(
                prices_by_region,
                {
                    "db.m5.large": frozenset({"Single-AZ", "Multi-AZ"}),
                    "db.r6gd.xlarge": frozenset({"Single-AZ"}),
                },
            ),
        ),
        patch(
            "sc_crawler.vendors._aws._boto_describe_db_major_engine_versions_first",
            return_value=["15", "16"],
        ),
        patch(
            "sc_crawler.vendors._aws._lookup_orderable_db_instance_options",
            return_value=options_by_database,
        ),
    ):
        rows = aws_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert set(by_id) == {"db.m5.large", "db.r6gd.xlarge"}
    assert by_id["db.m5.large"]["server_id"] == "m5.large"
    assert by_id["db.m5.large"]["family"] == "General Purpose"
    assert by_id["db.m5.large"]["series"] == "m5"
    assert by_id["db.m5.large"]["compatible_storage_ids"] == ["gp3"]
    assert by_id["db.r6gd.xlarge"]["compatible_storage_ids"] == []
    assert by_id["db.r6gd.xlarge"]["family"] == "Memory Optimized"
    assert by_id["db.r6gd.xlarge"]["series"] == "r6gd"
    assert by_id["db.m5.large"]["memory_amount"] == 8 * 1024
    assert by_id["db.m5.large"]["storage_size"] is None
    assert by_id["db.m5.large"]["description"] == (
        "General purpose (2 vCPU, 8.0 GiB RAM)"
    )
    assert by_id["db.m5.large"]["ha"] == [
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.NONE,
    ]
    assert by_id["db.m5.large"]["ha_strategy"] == [
        DatabaseHaStrategy.PASSIVE_STANDBY,
        DatabaseHaStrategy.NONE,
    ]
    assert by_id["db.m5.large"]["api_reference_object"] == {
        "instance_class": "db.m5.large"
    }
    assert by_id["db.m5.large"]["storage_extra_autosize"] is True
    assert by_id["db.m5.large"]["storage_extra_min"] == 21
    assert by_id["db.m5.large"]["storage_extra_max"] == 70369
    assert by_id["db.m5.large"]["disk_encryption"] is True
    assert by_id["db.m5.large"]["system_monitoring"] is True
    assert by_id["db.m5.large"]["database_monitoring"] is True
    assert by_id["db.m5.large"]["custom_config"] is True
    assert by_id["db.m5.large"]["custom_extensions"] is True
    assert by_id["db.m5.large"]["auto_upgrade_versions"] is True
    assert by_id["db.m5.large"]["autotuning_advice"] is True
    assert by_id["db.m5.large"]["autotuning_apply"] is False
    assert by_id["db.m5.large"]["max_read_replicas"] == 15
    assert by_id["db.m5.large"]["connection_pool"] is True
    assert by_id["db.m5.large"]["sla"] == 99.95
    assert by_id["db.m5.large"]["engine"] == DatabaseEngine.POSTGRESQL
    assert by_id["db.m5.large"]["wire_protocol"] == DatabaseWireProtocol.POSTGRESQL
    assert by_id["db.m5.large"]["engine_versions"] == ["15", "16"]
    assert by_id["db.m5.large"]["scheduled_backups"] is True
    assert by_id["db.m5.large"]["continuous_backups"] == 35
    assert by_id["db.m5.large"]["security_features"] == [
        DatabaseSecurityFeature.IP_FILTERING,
        DatabaseSecurityFeature.PRIVATE_NETWORK,
        DatabaseSecurityFeature.NETWORK_PEERING,
        DatabaseSecurityFeature.IDENTITY_BASED_AUTH,
        DatabaseSecurityFeature.ENFORCED_TLS,
        DatabaseSecurityFeature.CUSTOMER_MANAGED_KEYS,
        DatabaseSecurityFeature.AUDIT_LOGGING,
    ]
    assert (
        DatabaseSecurityFeature.CLIENT_CERT_AUTH
        not in by_id["db.m5.large"]["security_features"]
    )
    assert by_id["db.r6gd.xlarge"]["server_id"] == "r6gd.xlarge"
    assert by_id["db.r6gd.xlarge"]["storage_size"] == 127
    assert by_id["db.r6gd.xlarge"]["description"] == (
        "Memory optimized (4 vCPU, 32.0 GiB RAM, 127 GB NVMe SSD)"
    )
    assert by_id["db.r6gd.xlarge"]["ha"] == [DatabaseHaLevel.NONE]
    assert by_id["db.r6gd.xlarge"]["ha_strategy"] == [DatabaseHaStrategy.NONE]
    assert by_id["db.r6gd.xlarge"]["sla"] == 99.5
    assert by_id["db.r6gd.xlarge"]["max_read_replicas"] == 0


def test_aws_inventory_databases_ignores_supports_global_databases_for_postgres():
    """SupportsGlobalDatabases is Aurora-only; RDS postgres falls through to Multi-AZ."""
    vendor = _aws_vendor(
        regions=[Mock(region_id="us-east-1", status=Status.ACTIVE)],
        servers=[],
    )
    prices_by_region = {
        "us-east-1": {
            "db.r5.large": {
                "instanceFamily": "Memory optimized",
                "vcpu": "2",
                "memory": "16 GiB",
                "storage": "EBS Only",
            },
        }
    }
    with (
        patch(
            "sc_crawler.vendors._aws._get_rds_instance_products_by_region",
            return_value=(
                prices_by_region,
                {"db.r5.large": frozenset({"Single-AZ", "Multi-AZ"})},
            ),
        ),
        patch(
            "sc_crawler.vendors._aws._boto_describe_db_major_engine_versions_first",
            return_value=["16"],
        ),
        patch(
            "sc_crawler.vendors._aws._lookup_orderable_db_instance_options",
            return_value={
                "db.r5.large": [
                    {
                        "MultiAZCapable": True,
                        "SupportsGlobalDatabases": True,
                        "SupportsStorageAutoscaling": True,
                        "MinStorageSize": 20,
                        "MaxStorageSize": 65536,
                        "SupportsStorageEncryption": True,
                        "SupportsEnhancedMonitoring": True,
                        "SupportsPerformanceInsights": True,
                        "ReadReplicaCapable": True,
                    }
                ]
            },
        ),
    ):
        rows = aws_databases(vendor)
    assert rows[0]["ha"] == [DatabaseHaLevel.MULTI_ZONE, DatabaseHaLevel.NONE]
    assert rows[0]["ha_strategy"] == [
        DatabaseHaStrategy.PASSIVE_STANDBY,
        DatabaseHaStrategy.NONE,
    ]
    assert rows[0]["sla"] == 99.95


def test_aws_inventory_databases_ha_readable_standbys_from_deployment_options():
    vendor = _aws_vendor(
        regions=[Mock(region_id="us-east-1", status=Status.ACTIVE)],
        servers=[],
    )
    prices_by_region = {
        "us-east-1": {
            "db.m5d.large": {
                "instanceFamily": "General purpose",
                "vcpu": "2",
                "memory": "8 GiB",
                "storage": "EBS Only",
            },
        }
    }
    with (
        patch(
            "sc_crawler.vendors._aws._get_rds_instance_products_by_region",
            return_value=(
                prices_by_region,
                {
                    "db.m5d.large": frozenset(
                        {"Single-AZ", "Multi-AZ", "Multi-AZ (readable standbys)"}
                    )
                },
            ),
        ),
        patch(
            "sc_crawler.vendors._aws._boto_describe_db_major_engine_versions_first",
            return_value=["16"],
        ),
        patch(
            "sc_crawler.vendors._aws._lookup_orderable_db_instance_options",
            return_value={
                "db.m5d.large": [
                    {
                        "MultiAZCapable": True,
                        "SupportsStorageAutoscaling": True,
                        "MinStorageSize": 20,
                        "MaxStorageSize": 65536,
                        "SupportsStorageEncryption": True,
                        "SupportsEnhancedMonitoring": True,
                        "SupportsPerformanceInsights": True,
                        "ReadReplicaCapable": True,
                    }
                ]
            },
        ),
    ):
        rows = aws_databases(vendor)
    assert rows[0]["ha"] == [DatabaseHaLevel.MULTI_ZONE, DatabaseHaLevel.NONE]
    assert rows[0]["ha_strategy"] == [
        DatabaseHaStrategy.READABLE_CLUSTER,
        DatabaseHaStrategy.PASSIVE_STANDBY,
        DatabaseHaStrategy.NONE,
    ]


def test_aws_inventory_databases_dedupes_across_regions():
    vendor = _aws_vendor(
        regions=[
            Mock(region_id="us-east-1", status=Status.ACTIVE),
            Mock(region_id="eu-west-1", status=Status.ACTIVE),
        ]
    )
    attrs = {
        "instanceFamily": "General purpose",
        "vcpu": "2",
        "memory": "8 GiB",
        "storage": "EBS Only",
    }
    with (
        patch(
            "sc_crawler.vendors._aws._get_rds_instance_products_by_region",
            return_value=(
                {
                    "us-east-1": {"db.m5.large": attrs},
                    "eu-west-1": {"db.m5.large": attrs},
                },
                {"db.m5.large": frozenset({"Single-AZ", "Multi-AZ"})},
            ),
        ),
        patch(
            "sc_crawler.vendors._aws._boto_describe_db_major_engine_versions_first",
            return_value=["16"],
        ),
        patch(
            "sc_crawler.vendors._aws._lookup_orderable_db_instance_options",
            return_value={
                "db.m5.large": [
                    {
                        "MultiAZCapable": True,
                        "SupportsStorageAutoscaling": True,
                        "MinStorageSize": 20,
                        "MaxStorageSize": 65536,
                        "SupportsStorageEncryption": True,
                        "SupportsEnhancedMonitoring": True,
                        "SupportsPerformanceInsights": True,
                        "ReadReplicaCapable": True,
                    }
                ]
            },
        ),
    ):
        rows = aws_databases(vendor)
    assert [row["database_id"] for row in rows] == ["db.m5.large"]


def test_aws_inventory_databases_status_from_orderable_options_and_end_of_support():
    vendor = _aws_vendor(
        regions=[Mock(region_id="us-east-1", status=Status.ACTIVE)],
    )
    prices_by_region = {
        "us-east-1": {
            "db.m5.large": {
                "instanceFamily": "General purpose",
                "vcpu": "2",
                "memory": "8 GiB",
                "storage": "EBS Only",
            },
            "db.m4.large": {
                "instanceFamily": "General purpose",
                "vcpu": "2",
                "memory": "8 GiB",
                "storage": "EBS Only",
            },
            "db.m6g.large": {
                "instanceFamily": "General purpose",
                "vcpu": "2",
                "memory": "8 GiB",
                "storage": "EBS Only",
            },
            "db.t2.micro": {
                "instanceFamily": "General purpose",
                "vcpu": "1",
                "memory": "1 GiB",
                "storage": "EBS Only",
            },
            "db.t1.micro": {
                "instanceFamily": "General purpose",
                "vcpu": "1",
                "memory": "1 GiB",
                "storage": "EBS Only",
            },
        }
    }
    orderable = {
        "MultiAZCapable": True,
        "SupportsStorageAutoscaling": True,
        "MinStorageSize": 20,
        "MaxStorageSize": 65536,
        "SupportsStorageEncryption": True,
        "SupportsEnhancedMonitoring": True,
        "SupportsPerformanceInsights": True,
        "ReadReplicaCapable": True,
    }
    with (
        patch(
            "sc_crawler.vendors._aws._get_rds_instance_products_by_region",
            return_value=(
                prices_by_region,
                {
                    "db.m5.large": frozenset({"Single-AZ", "Multi-AZ"}),
                    "db.m4.large": frozenset({"Single-AZ", "Multi-AZ"}),
                    "db.m6g.large": frozenset({"Single-AZ", "Multi-AZ"}),
                    "db.t2.micro": frozenset({"Single-AZ", "Multi-AZ"}),
                    "db.t1.micro": frozenset({"Single-AZ", "Multi-AZ"}),
                },
            ),
        ),
        patch(
            "sc_crawler.vendors._aws._boto_describe_db_major_engine_versions_first",
            return_value=["16"],
        ),
        patch(
            "sc_crawler.vendors._aws._lookup_orderable_db_instance_options",
            return_value={
                "db.m5.large": [orderable],
                "db.m4.large": [orderable],
                "db.m6g.large": [],
                "db.t2.micro": [],
                "db.t1.micro": [],
            },
        ),
    ):
        rows = aws_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert by_id["db.m5.large"]["status"] == Status.ACTIVE
    # orderable -> ACTIVE (no end-of-support family mapping in current code)
    assert by_id["db.m4.large"]["status"] == Status.ACTIVE
    assert by_id["db.m6g.large"]["status"] == Status.RETIRED
    # not orderable wins over the end-of-support mapping
    assert by_id["db.t2.micro"]["status"] == Status.RETIRED
    # not orderable classes are retired without being mapped
    assert by_id["db.t1.micro"]["status"] == Status.RETIRED


def test_aws_inventory_server_prices_deactivates_unoffered_instance_types():
    region = Mock(
        region_id="us-east-1",
        api_reference="us-east-1",
        aliases=[],
        status=Status.ACTIVE,
    )
    region.name = "US East (N. Virginia)"
    m5 = _aws_server_mock("m5.large", Status.ACTIVE)
    t1 = _aws_server_mock("t1.micro", Status.ACTIVE)
    mac = _aws_server_mock("mac1.metal", Status.ACTIVE)
    vendor = _aws_vendor(regions=[region], servers=[m5, t1, mac])
    products = [
        {
            "product": {
                "attributes": {
                    "location": "US East (N. Virginia)",
                    "instanceType": "m5.large",
                }
            },
            "terms": _aws_ondemand_terms("0.096"),
        },
        {
            "product": {
                "attributes": {
                    "location": "US East (N. Virginia)",
                    "instanceType": "t1.micro",
                }
            },
            "terms": _aws_ondemand_terms("0.02"),
        },
    ]
    with (
        patch(
            "sc_crawler.vendors._aws._boto_get_products",
            return_value=products,
        ),
        patch(
            "sc_crawler.vendors._aws._describe_instance_type_offerings_per_zone_with_progress",
            return_value={
                "m5.large": ["use1-az1"],
                "mac1.metal": ["use1-az1"],
            },
        ),
    ):
        prices = aws_server_prices(vendor)
        aws_reconcile_server_status(vendor)
    assert {(p["server_id"], p["zone_id"]) for p in prices} == {
        ("m5.large", "use1-az1")
    }
    assert m5.status == Status.ACTIVE
    # still priced, but not offered in any zone
    assert t1.status == Status.INACTIVE
    # offered, even without a Linux on-demand SKU
    assert mac.status == Status.ACTIVE


def _aws_server_mock(server_id, status, accelerator_count=0):
    return Mock(
        server_id=server_id,
        status=status,
        accelerator_count=accelerator_count,
        accelerator_type=None,
    )


def test_aws_reconcile_server_status_keeps_spot_only_instance_types_active():
    region = Mock(
        region_id="us-east-1",
        api_reference="us-east-1",
        aliases=[],
        status=Status.ACTIVE,
    )
    region.name = "US East (N. Virginia)"
    spot_only = _aws_server_mock("p4d.24xlarge", Status.INACTIVE)
    vendor = _aws_vendor(regions=[region], servers=[spot_only])
    with patch(
        "sc_crawler.vendors._aws._describe_instance_type_offerings_per_zone_with_progress",
        return_value={},
    ):
        aws_reconcile_server_status(vendor, spot_server_ids={"p4d.24xlarge"})
    assert spot_only.status == Status.ACTIVE


def test_aws_reconcile_server_status_sets_missing_accelerator_type_of_active_servers():
    region = Mock(
        region_id="us-east-1",
        api_reference="us-east-1",
        aliases=[],
        status=Status.ACTIVE,
    )
    region.name = "US East (N. Virginia)"
    # spot-only GPU server last crawled before accelerator_type was introduced
    gpu_active = _aws_server_mock("g4ad.xlarge", Status.INACTIVE, 1)
    gpu_inactive = _aws_server_mock("p3.2xlarge", Status.ACTIVE, 1)
    no_gpu = _aws_server_mock("m5.large", Status.INACTIVE)
    vendor = _aws_vendor(regions=[region], servers=[gpu_active, gpu_inactive, no_gpu])
    with patch(
        "sc_crawler.vendors._aws._describe_instance_type_offerings_per_zone_with_progress",
        return_value={"m5.large": ["use1-az1"]},
    ):
        aws_reconcile_server_status(vendor, spot_server_ids={"g4ad.xlarge"})
    assert gpu_active.status == Status.ACTIVE
    assert gpu_active.accelerator_type == AcceleratorType.GPU
    assert gpu_inactive.status == Status.INACTIVE
    assert gpu_inactive.accelerator_type is None
    assert no_gpu.status == Status.ACTIVE
    assert no_gpu.accelerator_type is None


def test_aws_inventory_database_prices_by_ha_deployment():
    vendor = _aws_vendor(
        regions=[Mock(region_id="us-east-1", status=Status.ACTIVE)],
        databases=[Mock(database_id="db.m5.large", status=Status.ACTIVE)],
    )
    products = [
        _aws_rds_instance_product(
            instance_type="db.m5.large", region="us-east-1", price="0.145"
        ),
        _aws_rds_instance_product(
            instance_type="db.m5.large",
            region="us-east-1",
            deployment="Multi-AZ",
            price="0.29",
        ),
        _aws_rds_instance_product(
            instance_type="db.m5.large",
            region="us-east-1",
            deployment="Multi-AZ (readable standbys)",
            price="0.435",
        ),
        _aws_rds_instance_product(
            instance_type="db.m5.large",
            region="ap-south-1",
            price="0.16",
        ),
        _aws_rds_instance_product(
            instance_type="db.t2.micro", region="us-east-1", price="0.017"
        ),
        _aws_rds_storage_product(volume_type="General Purpose-GP3"),
    ]
    with patch(
        "sc_crawler.vendors._aws._boto_get_rds_products",
        return_value=products,
    ):
        prices = aws_database_prices(vendor)
    assert len(prices) == 3
    by_ha = {(row["ha"], row["ha_strategy"]): row for row in prices}
    assert (
        by_ha[(DatabaseHaLevel.SINGLE_ZONE, DatabaseHaStrategy.NONE)]["price"] == 0.145
    )
    assert (
        by_ha[(DatabaseHaLevel.MULTI_ZONE, DatabaseHaStrategy.PASSIVE_STANDBY)]["price"]
        == 0.29
    )
    assert (
        by_ha[(DatabaseHaLevel.MULTI_ZONE, DatabaseHaStrategy.READABLE_CLUSTER)][
            "price"
        ]
        == 0.435
    )
    assert prices[0]["database_id"] == "db.m5.large"
    assert prices[0]["region_id"] == "us-east-1"
    assert prices[0]["allocation"] == Allocation.ONDEMAND
    assert prices[0]["unit"] == PriceUnit.HOUR
    assert prices[0]["currency"] == "USD"


def test_aws_inventory_database_storages_from_orderable_bounds():
    vendor = _aws_vendor(
        regions=[Mock(region_id="us-east-1", status=Status.ACTIVE)],
    )
    with (
        patch(
            "sc_crawler.vendors._aws._get_rds_instance_products_by_region",
            return_value=({"us-east-1": {"db.m5.large": {}}}, {}),
        ),
        patch(
            "sc_crawler.vendors._aws._lookup_orderable_db_instance_options",
            return_value={
                "db.m5.large": [
                    {
                        "StorageType": "gp3",
                        "MinStorageSize": 20,
                        "MaxStorageSize": 65536,
                        "MaxIopsPerDbInstance": 64000,
                        "MaxStorageThroughputPerDbInstance": 4000,
                    },
                    {
                        "StorageType": "io1",
                        "MinStorageSize": 100,
                        "MaxStorageSize": 65536,
                        "MaxIopsPerDbInstance": 80000,
                        "MaxStorageThroughputPerDbInstance": 2000,
                    },
                ]
            },
        ),
    ):
        storages = aws_database_storages(vendor)
    by_id = {row["database_storage_id"]: row for row in storages}
    assert set(by_id) == {"gp3", "io1"}
    assert by_id["gp3"]["name"] == "General Purpose-GP3"
    assert by_id["gp3"]["description"] == "SSD-backed"
    assert by_id["gp3"]["min_size"] == 21
    assert by_id["gp3"]["max_size"] == 70369
    assert by_id["gp3"]["max_iops"] == 64000
    assert by_id["gp3"]["max_throughput"] == 4000
    assert "standard" not in by_id


def test_aws_inventory_database_storage_prices_skip_missing_catalog():
    vendor = _aws_vendor(
        regions=[
            Mock(region_id="us-east-1", status=Status.ACTIVE),
            Mock(region_id="eu-west-1", status=Status.ACTIVE),
        ],
        database_storages=[
            Mock(database_storage_id="gp3"),
            Mock(database_storage_id="gp2"),
        ],
    )
    products = [
        _aws_rds_storage_product(volume_type="General Purpose-GP3", price="0.08"),
        _aws_rds_storage_product(volume_type="Magnetic", price="0.10"),
        _aws_rds_storage_product(volume_type="General Purpose", region="eu-west-1"),
        _aws_rds_storage_product(
            volume_type="General Purpose-GP3",
            region="us-east-1",
            deployment="Multi-AZ",
            price="0.16",
        ),
        _aws_rds_storage_product(
            volume_type="General Purpose-GP3", region="ap-south-1", price="0.09"
        ),
        _aws_rds_instance_product(instance_type="db.m5.large"),
    ]
    with patch(
        "sc_crawler.vendors._aws._boto_get_rds_products",
        return_value=products,
    ):
        prices = aws_database_storage_prices(vendor)
    assert len(prices) == 2
    assert {(p["database_storage_id"], p["region_id"], p["price"]) for p in prices} == {
        ("gp3", "us-east-1", 0.08),
        ("gp2", "eu-west-1", 0.115),
    }
    assert prices[0]["unit"] == PriceUnit.GB_MONTH


@pytest.mark.parametrize(
    ("instance_type", "series", "family"),
    [
        ("m5.large", "m5", "General Purpose"),
        ("t4g.micro", "t4g", "General Purpose"),
        # not in the Pricing API, categories from the docs dict
        ("mac2-m1ultra.metal", "mac2-m1ultra", "General Purpose"),
        ("trn2u.48xlarge", "trn2u", "Accelerated Computing"),
        ("u7inh-32tb.480xlarge", "u7inh-32tb", "Memory Optimized"),
        ("c7i-flex.large", "c7i-flex", "Compute Optimized"),
        ("r8g.xlarge", "r8g", "Memory Optimized"),
        ("u-12tb1.112xlarge", "u-12tb1", "Memory Optimized"),
        ("i4i.large", "i4i", "Storage Optimized"),
        ("p5.48xlarge", "p5", "Accelerated Computing"),
        ("p6-b200.48xlarge", "p6-b200", "Accelerated Computing"),
        ("trn2.48xlarge", "trn2", "Accelerated Computing"),
        ("hpc7a.96xlarge", "hpc7a", "High-Performance Computing"),
        # retired types, still listed by the Pricing API
        ("f1.2xlarge", "f1", "Accelerated Computing"),
        ("g3s.xlarge", "g3s", "Accelerated Computing"),
        ("p2.xlarge", "p2", "Accelerated Computing"),
        # series not (yet) classified
        ("brandnew1.large", "brandnew1", None),
    ],
)
def test_aws_instance_series_and_family(instance_type, series, family):
    assert _instance_series(instance_type) == series
    assert _instance_family(instance_type) == family


@pytest.mark.parametrize(
    ("database_id", "pricing_family", "family"),
    [
        # same category as the EC2 instance type, even if the pricing API differs
        ("db.m5.large", "General purpose", "General Purpose"),
        ("db.m8gd.large", "Memory optimized", "General Purpose"),
        ("db.t1.micro", "Micro instances", "General Purpose"),
        # not an EC2 instance type: Title Case category of the pricing API
        ("db.x2g.large", "Memory optimized", "Memory Optimized"),
    ],
)
def test_aws_database_family(database_id, pricing_family, family):
    assert _database_family(database_id, pricing_family) == family


def _product(instance_type, category=None):
    attributes = {"instanceType": instance_type}
    if category:
        attributes["instanceFamilyCategory"] = category
    return {"product": {"attributes": attributes}}


def test_aws_server_series_categories_from_pricing_products():
    _server_series_categories.cache_clear()
    products = [
        _product("m5n.large", "General Purpose"),
        _product("m5n.xlarge", "General Purpose"),
        _product("i7ie.large", "Storage Optimized"),
        _product("p6-b200.48xlarge", "Accelerated Computing"),
        # no category: ignored
        _product("nocategory.large"),
        # no instance type, e.g. other products
        {"product": {"attributes": {"instanceFamilyCategory": "General Purpose"}}},
    ]
    with patch("sc_crawler.vendors._aws._get_server_products", return_value=products):
        categories = _server_series_categories()
    _server_series_categories.cache_clear()
    assert categories == {
        "m5n": "General Purpose",
        "i7ie": "Storage Optimized",
        "p6-b200": "Accelerated Computing",
    }


def test_aws_pricing_api_category_wins_and_docs_dict_is_the_fallback():
    categories = {"m5": "Compute Optimized", "newgen1": "Memory Optimized"}
    with patch(
        "sc_crawler.vendors._aws._server_series_categories", return_value=categories
    ):
        # the Pricing API wins over the docs dict
        assert _instance_family("m5.large") == "Compute Optimized"
        # a series missing from the docs dict gets its category from the API
        assert _instance_family("newgen1.large") == "Memory Optimized"
        # a series missing from the API falls back to the docs dict, e.g. Mac
        assert _instance_family("mac2-m2.metal") == "General Purpose"
        # RDS uses the category of the EC2 series
        assert _database_family("db.newgen1.large", "General purpose") == (
            "Memory Optimized"
        )


def test_aws_pricing_api_failure_falls_back_to_the_docs_dict():
    _server_series_categories.cache_clear()
    with (
        patch(
            "sc_crawler.vendors._aws._get_server_products",
            side_effect=RuntimeError("no access"),
        ),
        patch("sc_crawler.vendors._aws.logger") as logger,
    ):
        assert _server_series_categories() == {}
    _server_series_categories.cache_clear()
    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert len(warnings) == 1
    assert "no access" in warnings[0]


def test_aws_unknown_family_is_empty_and_warned_once():
    _warn_unknown_family.cache_clear()
    with patch("sc_crawler.vendors._aws.logger") as logger:
        assert _instance_family("brandnew1.large") is None
        assert _instance_family("brandnew1.xlarge") is None
        # known series do not warn
        assert _instance_family("m5.large") == "General Purpose"
        # the RDS fallback to the pricing family does not warn
        assert _database_family("db.brandnew1.large", "Memory optimized") == (
            "Memory Optimized"
        )
    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert len(warnings) == 1
    assert "brandnew1" in warnings[0]


def test_aws_server_products_are_cached_in_memory():
    _get_server_products.cache_clear()
    with patch(
        "sc_crawler.vendors._aws._boto_get_products", return_value=[]
    ) as get_products:
        _get_server_products()
        _get_server_products()
    _get_server_products.cache_clear()
    get_products.assert_called_once()


def test_aws_compatible_storage_ids_are_all_ebs_types_if_ebs_can_be_attached():
    all_ids = ["standard", "gp2", "gp3", "st1", "sc1", "io1", "io2"]
    # an old Xen and a Nitro instance type, both can attach EBS volumes
    for ebs_info in (
        {"EbsOptimizedSupport": "unsupported", "MaximumEbsAttachments": 3},
        {"EbsOptimizedSupport": "default", "MaximumEbsAttachments": 27},
    ):
        assert _compatible_storage_ids({"EbsInfo": ebs_info}) == all_ids
    # no EBS volume can be attached
    assert _compatible_storage_ids({"EbsInfo": {"MaximumEbsAttachments": 0}}) == []
    assert _compatible_storage_ids({}) == []


def test_aws_database_compatible_storage_ids_from_orderable_options():
    options = [
        {"StorageType": "io2"},
        {"StorageType": "gp3"},
        {"StorageType": "gp2"},
        {"StorageType": "gp3"},
        # not a known database storage: ignored
        {"StorageType": "aurora"},
        {},
    ]
    # in the order of the database storage mapping, without duplicates
    assert _database_compatible_storage_ids(options) == ["gp2", "gp3", "io2"]
    assert _database_compatible_storage_ids([]) == []
