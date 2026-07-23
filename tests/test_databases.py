from types import SimpleNamespace
from unittest.mock import Mock, patch

from sc_crawler.table_fields import Allocation, DatabaseEngine, PriceUnit, Status
from sc_crawler.vendor_helpers import merge_database_catalog_rows
from sc_crawler.vendors._aws import (
    _active_region_ids,
    _boto_describe_db_major_engine_versions_first,
    _extract_rds_storage_size,
    _get_rds_instance_products_by_region,
    _get_storage_bounds_from_orderable_options,
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
from sc_crawler.vendors._azure import (
    _pg_database_regions,
    _pg_engine_versions,
    _pg_lookup_retail_price,
)
from sc_crawler.vendors._azure import (
    inventory_database_storage_prices as azure_database_storage_prices,
)
from sc_crawler.vendors._gcp import (
    _pg_storage_id,
    inventory_database_prices,
    inventory_databases,
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
    price: str = "0.115",
) -> dict:
    return {
        "product": {
            "productFamily": "Database Storage",
            "attributes": {
                "volumeType": volume_type,
                "regionCode": region,
            },
        },
        "terms": _aws_ondemand_terms(price),
    }


def _aws_vendor(*, regions=None, servers=None, database_storages=None):
    vendor = Mock(vendor_id="aws")
    vendor.regions = regions or []
    vendor.servers = servers or []
    vendor.database_storages = database_storages or []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    return vendor


def _gcp_pg_sku(description: str, *, regions: list[str], units: int, nanos: int):
    return SimpleNamespace(
        description=description,
        service_regions=regions,
        pricing_info=[
            SimpleNamespace(
                pricing_expression=SimpleNamespace(
                    tiered_rates=[
                        SimpleNamespace(
                            unit_price=SimpleNamespace(
                                units=units,
                                nanos=nanos,
                                currency_code="USD",
                            )
                        )
                    ],
                    usage_unit="h",
                )
            )
        ],
    )


def test_pg_database_regions_filters_unsupported_locations():
    vendor = Mock(vendor_id="azure")
    vendor.regions = [
        Mock(
            region_id="centralus",
            api_reference="centralus",
            aliases=["Central US"],
        ),
        Mock(
            region_id="australiacentral2",
            api_reference="australiacentral2",
            aliases=["Australia Central 2"],
        ),
    ]
    with patch(
        "sc_crawler.vendors._azure._resources",
        return_value=[
            {
                "resourceType": "locations/capabilities",
                "locations": ["Central US", "East US"],
            }
        ],
    ):
        regions = _pg_database_regions(vendor)
    assert [region.api_reference for region in regions] == ["centralus"]


def test_pg_database_regions_falls_back_when_provider_missing():
    vendor = Mock(vendor_id="azure")
    vendor.regions = [
        Mock(region_id="centralus", api_reference="centralus", aliases=["Central US"]),
    ]
    with patch("sc_crawler.vendors._azure._resources", return_value=[]):
        regions = _pg_database_regions(vendor)
    assert [region.api_reference for region in regions] == ["centralus"]


def test_pg_lookup_retail_price_uses_capability_database_id():
    prices_by_arm = {
        "B1MS": [
            {
                "armSkuName": "B1MS",
                "productName": (
                    "Azure Database for PostgreSQL Flexible Server "
                    "Burstable BS Series Compute"
                ),
                "meterName": "B1MS",
                "retailPrice": "0.018",
            }
        ],
        "Standard_D16ads_v5": [
            {
                "armSkuName": "Standard_D16ads_v5",
                "productName": (
                    "Azure Database for PostgreSQL Flexible Server "
                    "General Purpose AMD Dadsv5 Series Compute"
                ),
                "meterName": "D16ads v5",
                "retailPrice": "1.008",
            }
        ],
    }

    burstable = _pg_lookup_retail_price(
        database_id="Standard_B1ms",
        edition_name="Burstable",
        prices_by_arm=prices_by_arm,
    )
    assert burstable is not None
    assert burstable["armSkuName"] == "B1MS"

    general = _pg_lookup_retail_price(
        database_id="Standard_D16ads_v5",
        edition_name="GeneralPurpose",
        prices_by_arm=prices_by_arm,
    )
    assert general is not None
    assert general["armSkuName"] == "Standard_D16ads_v5"


def test_pg_storage_prices_skip_unsupported_retail_meters():
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="centralus", api_reference="centralus")]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    ultra_disk_retail = {
        "productName": "Az DB for PostgreSQL Flexible Server Storage",
        "meterName": "Ultra Disk Storage Data Stored",
        "unitOfMeasure": "1 GB/Month",
        "retailPrice": "0.25",
        "currencyCode": "USD",
    }
    managed_disk_retail = {
        "productName": "Az DB for PostgreSQL Flexible Server Storage",
        "meterName": "Storage Data Stored",
        "unitOfMeasure": "1 GB/Month",
        "retailPrice": "0.115",
        "currencyCode": "USD",
    }
    backup_retail = {
        "productName": "Azure Database for PostgreSQL Flexible Server Backup Storage",
        "meterName": "Backup Storage LRS Data Stored",
        "unitOfMeasure": "1 GB/Month",
        "retailPrice": "0.095",
        "currencyCode": "USD",
    }
    capability = SimpleNamespace(
        supported_server_editions=[
            SimpleNamespace(
                supported_storage_editions=[
                    SimpleNamespace(
                        name="ManagedDisk",
                        reason=None,
                    ),
                    SimpleNamespace(
                        name="UltraDisk",
                        reason="Specified Storage Edition not supported in this region.",
                    ),
                ]
            )
        ]
    )
    with (
        patch(
            "sc_crawler.vendors._azure._pg_database_regions",
            return_value=vendor.regions,
        ),
        patch(
            "sc_crawler.vendors._azure._pg_capabilities",
            return_value=[capability],
        ),
        patch(
            "sc_crawler.vendors._azure._pg_retail_prices",
            return_value=[ultra_disk_retail, managed_disk_retail, backup_retail],
        ),
    ):
        prices = azure_database_storage_prices(vendor)
    storage_ids = {row["database_storage_id"] for row in prices}
    assert storage_ids == {"ManagedDisk", "BackupStorageLRS"}


def test_pg_engine_versions_from_capability():
    capability = SimpleNamespace(
        supported_server_versions=[
            SimpleNamespace(name="15", status="Available"),
            SimpleNamespace(name="16", status="Available"),
            SimpleNamespace(name="14", status="Disabled"),
            SimpleNamespace(name=None, status="Available"),
        ]
    )
    assert _pg_engine_versions(capability) == ["15", "16"]


def test_merge_database_catalog_rows_merges_versions():
    rows = merge_database_catalog_rows(
        [
            {
                "database_id": "pg_a",
                "engine_versions": ["15"],
                "ha_supported": False,
            },
            {
                "database_id": "pg_a",
                "engine_versions": ["16"],
                "ha_supported": True,
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["engine_versions"] == ["15", "16"]
    assert rows[0]["ha_supported"] is True


def test_gcp_tier_pricing_from_billing_fixture():
    # 0.0413 vCPU * 4 + 0.007 RAM * 15 GiB = 0.2702
    skus = [
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Zonal - vCPU in Americas",
            regions=["us-central1"],
            units=0,
            nanos=41_300_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Zonal - RAM in Americas",
            regions=["us-central1"],
            units=0,
            nanos=7_000_000,
        ),
    ]
    vendor = Mock(vendor_id="gcp")
    vendor.regions = [Mock(region_id="1", api_reference="us-central1")]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    tiers = [
        {
            "tier": "db-n1-standard-4",
            "RAM": "16106127360",
            "region": ["us-central1"],
        }
    ]
    with (
        patch("sc_crawler.vendors._gcp._cloud_sql_skus", return_value=skus),
        patch(
            "sc_crawler.vendors._gcp._pg_sqladmin_metadata",
            return_value={"tiers": tiers},
        ),
    ):
        prices = inventory_database_prices(vendor)
    assert len(prices) == 1
    assert prices[0]["database_id"] == "db-n1-standard-4"
    assert abs(prices[0]["price"] - 0.2702) < 0.001
    assert prices[0]["currency"] == "USD"
    assert (
        _pg_storage_id(
            "Cloud SQL for PostgreSQL: Zonal - Enterprise Plus Standard Storage in Iowa"
        )
        == "cloudsql-ssd"
    )
    assert (
        _pg_storage_id("Cloud SQL for PostgreSQL: Zonal - Standard storage in Americas")
        == "cloudsql-ssd-standard"
    )
    assert (
        _pg_storage_id("Cloud SQL for PostgreSQL: Zonal - Low cost storage in Americas")
        == "cloudsql-hdd"
    )
    assert (
        _pg_storage_id(
            "Cloud SQL for Postgres: Zonal - Enterprise Storage Hyperdisk Balanced Capacity in Iowa"
        )
        == "cloudsql-hyperdisk"
    )


def test_gcp_tier_description():
    vendor = Mock(vendor_id="gcp")
    vendor.regions = []
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    tiers = [
        {"tier": "db-n1-standard-4", "RAM": "16106127360", "region": ["us-central1"]},
        {"tier": "db-f1-micro", "RAM": "644245094", "region": ["us-central1"]},
    ]
    with (
        patch(
            "sc_crawler.vendors._gcp._pg_sqladmin_metadata",
            return_value={
                "tiers": tiers,
                "engine_versions": ["16"],
                "custom_config": True,
                "custom_extensions": True,
            },
        ),
        patch(
            "sc_crawler.vendors._gcp._pg_billing_catalog",
            return_value=({}, frozenset()),
        ),
    ):
        rows = inventory_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert (
        by_id["db-n1-standard-4"]["description"]
        == "PostgreSQL Cloud SQL N1 Standard (4 vCPUs, 15 GB RAM)"
    )
    assert (
        by_id["db-f1-micro"]["description"]
        == "PostgreSQL Cloud SQL Shared f1-micro (0.6 GB RAM)"
    )
    assert by_id["db-n1-standard-4"]["storage_size"] is None


def test_gcp_database_prices_use_region_name_not_numeric_id():
    skus = [
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Zonal - vCPU in Americas",
            regions=["us-central1"],
            units=0,
            nanos=41_300_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Zonal - RAM in Americas",
            regions=["us-central1"],
            units=0,
            nanos=7_000_000,
        ),
    ]
    vendor = Mock(vendor_id="gcp")
    vendor.regions = [Mock(region_id="999", api_reference="us-central1")]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    tiers = [
        {
            "tier": "db-n1-standard-4",
            "RAM": "16106127360",
            "region": ["us-central1"],
        }
    ]
    with (
        patch("sc_crawler.vendors._gcp._cloud_sql_skus", return_value=skus),
        patch(
            "sc_crawler.vendors._gcp._pg_sqladmin_metadata",
            return_value={"tiers": tiers},
        ),
    ):
        prices = inventory_database_prices(vendor)
    assert len(prices) == 1
    assert prices[0]["region_id"] == "999"
    assert prices[0]["database_id"] == "db-n1-standard-4"
    assert prices[0]["price"] > 0


def test_aws_extract_rds_storage_size():
    assert _extract_rds_storage_size(None) is None
    assert _extract_rds_storage_size("EBS Only") is None
    assert _extract_rds_storage_size("ebs only") is None
    assert _extract_rds_storage_size("2 x 1425 NVMe SSD") == 2850
    assert _extract_rds_storage_size("3 X 950 NVMe SSD") == 2850
    assert _extract_rds_storage_size("not a size") is None


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


def test_aws_instance_products_by_region_single_az_only():
    products = [
        _aws_rds_instance_product(instance_type="db.m5.large", region="us-east-1"),
        _aws_rds_instance_product(
            instance_type="db.m5.large",
            region="us-east-1",
            deployment="Multi-AZ",
            price="0.29",
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
        by_region = _get_rds_instance_products_by_region.__wrapped__()
    assert set(by_region) == {"us-east-1", "eu-west-1"}
    assert set(by_region["us-east-1"]) == {"db.m5.large"}
    assert by_region["eu-west-1"]["db.r6g.large"]["vcpu"] == "2"


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
    assert bounds["gp3"]["max_size"] == 65536
    assert bounds["gp3"]["max_iops"] == 64000
    assert bounds["gp3"]["max_throughput"] == 4000
    assert bounds["gp2"]["max_iops"] == 16000
    assert "standard" not in bounds


def test_aws_inventory_databases_description_server_id_and_capabilities():
    vendor = _aws_vendor(
        regions=[Mock(region_id="us-east-1", status=Status.ACTIVE)],
        servers=[Mock(server_id="m5.large"), Mock(server_id="r6gd.xlarge")],
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
            {"MultiAZCapable": True, "SupportsStorageAutoscaling": True},
        ],
        "db.r6gd.xlarge": [
            {"MultiAZCapable": False, "SupportsStorageAutoscaling": False},
        ],
    }
    with (
        patch(
            "sc_crawler.vendors._aws._get_rds_instance_products_by_region",
            return_value=prices_by_region,
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
    assert by_id["db.m5.large"]["memory_amount"] == 8 * 1024
    assert by_id["db.m5.large"]["storage_size"] is None
    assert by_id["db.m5.large"]["description"] == (
        "General purpose (2 vCPU, 8.0 GiB RAM)"
    )
    assert by_id["db.m5.large"]["ha_supported"] is True
    assert by_id["db.m5.large"]["storage_autoscaling"] is True
    assert by_id["db.m5.large"]["engine"] == DatabaseEngine.POSTGRESQL
    assert by_id["db.m5.large"]["engine_versions"] == ["15", "16"]
    assert by_id["db.m5.large"]["scheduled_backups"] is True
    assert by_id["db.m5.large"]["continuous_backups"] == 35
    assert by_id["db.r6gd.xlarge"]["server_id"] == "r6gd.xlarge"
    assert by_id["db.r6gd.xlarge"]["storage_size"] == 118
    assert by_id["db.r6gd.xlarge"]["description"] == (
        "Memory optimized (4 vCPU, 32.0 GiB RAM, 118 GB NVMe SSD)"
    )
    assert by_id["db.r6gd.xlarge"]["ha_supported"] is False


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
            return_value={
                "us-east-1": {"db.m5.large": attrs},
                "eu-west-1": {"db.m5.large": attrs},
            },
        ),
        patch(
            "sc_crawler.vendors._aws._boto_describe_db_major_engine_versions_first",
            return_value=["16"],
        ),
        patch(
            "sc_crawler.vendors._aws._lookup_orderable_db_instance_options",
            return_value={"db.m5.large": []},
        ),
    ):
        rows = aws_databases(vendor)
    assert [row["database_id"] for row in rows] == ["db.m5.large"]


def test_aws_inventory_database_prices_single_az_only():
    vendor = _aws_vendor()
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
        _aws_rds_storage_product(volume_type="General Purpose-GP3"),
    ]
    with patch(
        "sc_crawler.vendors._aws._boto_get_rds_products",
        return_value=products,
    ):
        prices = aws_database_prices(vendor)
    assert len(prices) == 1
    assert prices[0]["database_id"] == "db.m5.large"
    assert prices[0]["region_id"] == "us-east-1"
    assert prices[0]["price"] == 0.145
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
            return_value={"us-east-1": {"db.m5.large": {}}},
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
    assert by_id["gp3"]["min_size"] == 20
    assert by_id["gp3"]["max_size"] == 65536
    assert by_id["gp3"]["max_iops"] == 64000
    assert by_id["gp3"]["max_throughput"] == 4000
    assert "standard" not in by_id


def test_aws_inventory_database_storage_prices_skip_missing_catalog():
    vendor = _aws_vendor(
        database_storages=[
            Mock(database_storage_id="gp3"),
            Mock(database_storage_id="gp2"),
        ]
    )
    products = [
        _aws_rds_storage_product(volume_type="General Purpose-GP3", price="0.08"),
        _aws_rds_storage_product(volume_type="Magnetic", price="0.10"),
        _aws_rds_storage_product(volume_type="General Purpose", region="eu-west-1"),
        _aws_rds_instance_product(instance_type="db.m5.large"),
    ]
    with patch(
        "sc_crawler.vendors._aws._boto_get_rds_products",
        return_value=products,
    ):
        prices = aws_database_storage_prices(vendor)
    assert {(p["database_storage_id"], p["region_id"]) for p in prices} == {
        ("gp3", "us-east-1"),
        ("gp2", "eu-west-1"),
    }
    assert prices[0]["unit"] == PriceUnit.GB_MONTH
