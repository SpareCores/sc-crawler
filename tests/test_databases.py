import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sc_crawler.vendor_helpers import merge_database_catalog_rows
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
    fixture = Path(
        "/Users/sacrun/Projects/sc-scratch/attila/managed_dbs/vendor_data/azure/"
        "centralus/GetRetailPrices.json"
    )
    if not fixture.exists():
        return
    with fixture.open() as handle:
        items = json.load(handle)["Items"]
    prices_by_arm = {}
    for item in items:
        arm = item.get("armSkuName")
        if arm:
            prices_by_arm.setdefault(arm, []).append(item)

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
    fixture = Path(
        "/Users/sacrun/Projects/sc-scratch/attila/managed_dbs/vendor_data/gcp/global/"
        "cloudbilling.services.skus.json"
    )
    if not fixture.exists():
        return

    def sku_from_dict(data):
        pricing = []
        for pricing_info in data.get("pricingInfo", []):
            tiered = []
            for tier in pricing_info.get("pricingExpression", {}).get(
                "tieredRates", []
            ):
                unit_price = tier.get("unitPrice", {})
                tiered.append(
                    SimpleNamespace(
                        unit_price=SimpleNamespace(
                            units=int(unit_price.get("units", 0) or 0),
                            nanos=int(unit_price.get("nanos", 0) or 0),
                            currency_code=unit_price.get("currencyCode", "USD"),
                        )
                    )
                )
            pricing.append(
                SimpleNamespace(
                    pricing_expression=SimpleNamespace(
                        tiered_rates=tiered,
                        usage_unit=pricing_info.get("pricingExpression", {}).get(
                            "usageUnit", ""
                        ),
                    )
                )
            )
        return SimpleNamespace(
            description=data.get("description", ""),
            service_regions=data.get("serviceRegions", []),
            pricing_info=pricing,
        )

    skus = [sku_from_dict(item) for item in json.loads(fixture.read_text())["skus"]]
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


def test_gcp_database_prices_use_region_name_not_numeric_id():
    fixture = Path(
        "/Users/sacrun/Projects/sc-scratch/attila/managed_dbs/vendor_data/gcp/global/"
        "cloudbilling.services.skus.json"
    )
    if not fixture.exists():
        return

    def sku_from_dict(data):
        pricing = []
        for pricing_info in data.get("pricingInfo", []):
            tiered = []
            for tier in pricing_info.get("pricingExpression", {}).get(
                "tieredRates", []
            ):
                unit_price = tier.get("unitPrice", {})
                tiered.append(
                    SimpleNamespace(
                        unit_price=SimpleNamespace(
                            units=int(unit_price.get("units", 0) or 0),
                            nanos=int(unit_price.get("nanos", 0) or 0),
                            currency_code=unit_price.get("currencyCode", "USD"),
                        )
                    )
                )
            pricing.append(
                SimpleNamespace(
                    pricing_expression=SimpleNamespace(
                        tiered_rates=tiered,
                        usage_unit=pricing_info.get("pricingExpression", {}).get(
                            "usageUnit", ""
                        ),
                    )
                )
            )
        return SimpleNamespace(
            description=data.get("description", ""),
            service_regions=data.get("serviceRegions", []),
            pricing_info=pricing,
        )

    vendor = Mock(vendor_id="gcp")
    vendor.regions = [Mock(region_id="999", api_reference="us-central1")]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    skus = [sku_from_dict(item) for item in json.loads(fixture.read_text())["skus"]]
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
