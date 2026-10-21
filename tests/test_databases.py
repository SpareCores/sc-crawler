from types import SimpleNamespace
from unittest.mock import Mock, patch

from sc_crawler.table_fields import (
    DatabaseHaLevel,
    DatabaseHaStrategy,
    DatabaseSecurityFeature,
    Status,
)
from sc_crawler.vendors._azure import (
    _parse_database_name,
    _pg_database_regions,
    _pg_engine_versions,
    _pg_hourly_compute_price,
    _pg_lookup_retail_price,
)
from sc_crawler.vendors._azure import (
    inventory_database_storage_prices as azure_database_storage_prices,
)
from sc_crawler.vendors._gcp import (
    _gcp_machine_type_status,
    _pg_compute_sku_class,
    _pg_storage_id,
    inventory_database_prices,
    inventory_databases,
)


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
        vendor=Mock(),
        database_id="Standard_B1ms",
        edition_name="Burstable",
        prices_by_arm=prices_by_arm,
    )
    assert burstable is not None
    assert burstable["armSkuName"] == "B1MS"

    general = _pg_lookup_retail_price(
        vendor=Mock(),
        database_id="Standard_D16ads_v5",
        edition_name="GeneralPurpose",
        prices_by_arm=prices_by_arm,
    )
    assert general is not None
    assert general["armSkuName"] == "Standard_D16ads_v5"


def test_pg_lookup_retail_price_series_match_is_exact():
    """Dsv6 must not win when looking up Ddsv6 (substring false positive)."""
    prices_by_arm = {
        "Azure_Database_for_PostgreSQL_Flexible_Server_General_Purpose_Dsv6_Series_Compute_vCore": [
            {
                "armSkuName": (
                    "Azure_Database_for_PostgreSQL_Flexible_Server_"
                    "General_Purpose_Dsv6_Series_Compute_vCore"
                ),
                "productName": (
                    "Azure Database for PostgreSQL Flexible Server "
                    "General Purpose Dsv6 Series Compute"
                ),
                "skuName": "vCore",
                "meterName": "vCore",
                "retailPrice": 0.122,
            }
        ],
        "AzureDB_PostgreSQL_Flexible_Server_General_Purpose_Ddsv6_Series_Compute": [
            {
                "armSkuName": (
                    "AzureDB_PostgreSQL_Flexible_Server_"
                    "General_Purpose_Ddsv6_Series_Compute"
                ),
                "productName": (
                    "Azure Database for PostgreSQL Flexible Server "
                    "General Purpose Ddsv6 Series Compute"
                ),
                "skuName": "vCore",
                "meterName": "vCore",
                "retailPrice": 0.1535,
            }
        ],
    }

    ddsv6 = _pg_lookup_retail_price(
        vendor=Mock(),
        database_id="Standard_D16ds_v6",
        edition_name="GeneralPurpose",
        prices_by_arm=prices_by_arm,
    )
    assert ddsv6 is not None
    assert ddsv6["retailPrice"] == 0.1535
    assert "Ddsv6" in ddsv6["armSkuName"]

    dsv6 = _pg_lookup_retail_price(
        vendor=Mock(),
        database_id="Standard_D16s_v6",
        edition_name="GeneralPurpose",
        prices_by_arm=prices_by_arm,
    )
    assert dsv6 is not None
    assert dsv6["retailPrice"] == 0.122
    assert "Dsv6" in dsv6["armSkuName"]
    assert "Ddsv6" not in dsv6["armSkuName"]


def test_pg_lookup_retail_price_falls_back_to_one_vcore():
    """DCadsv6 has no full SKU meter; price is 1 vCore × database.vcpus."""
    one_vcore = {
        "armSkuName": "1 vCore",
        "productName": (
            "Azure Database for PostgreSQL Flexible Server "
            "Confidential Compute DCadsv6 Series Compute"
        ),
        "meterName": "1 vCore",
        "skuName": "1 vCore",
        "retailPrice": 0.112,
        "currencyCode": "USD",
    }
    prices_by_arm = {"1 vCore": [one_vcore]}
    item = _pg_lookup_retail_price(
        vendor=Mock(),
        database_id="Standard_DC16ads_v6",
        edition_name="DCadsv6",
        prices_by_arm=prices_by_arm,
    )
    assert item is one_vcore
    assert (
        _pg_hourly_compute_price(item, 16, database_id="Standard_DC16ads_v6") == 1.792
    )

    dsv6_per_vcore = {
        "armSkuName": "1 vCore",
        "productName": (
            "Azure Database for PostgreSQL Flexible Server "
            "General Purpose Dsv6 Series Compute"
        ),
        "meterName": "1 vCore",
        "skuName": "1 vCore",
        "retailPrice": 0.089,
    }
    ddsv6_per_vcore = {
        "armSkuName": "1 vCore",
        "productName": (
            "Azure Database for PostgreSQL Flexible Server "
            "General Purpose Ddsv6 Series Compute"
        ),
        "meterName": "1 vCore",
        "skuName": "1 vCore",
        "retailPrice": 0.112,
    }
    item = _pg_lookup_retail_price(
        vendor=Mock(),
        database_id="Standard_D16s_v6",
        edition_name="Dsv6",
        prices_by_arm={"1 vCore": [ddsv6_per_vcore, dsv6_per_vcore]},
    )
    assert item is dsv6_per_vcore

    # A full-instance meter wins over the per-vCore fallback.
    full_sku = {
        "armSkuName": "Standard_D16ds_v5",
        "productName": (
            "Azure Database for PostgreSQL Flexible Server "
            "General Purpose Ddsv5 Series Compute"
        ),
        "meterName": "vCore",
        "skuName": "16 vCore",
        "retailPrice": 1.424,
    }
    ddsv5_per_vcore = {
        "armSkuName": "1 vCore",
        "productName": (
            "Azure Database for PostgreSQL Flexible Server "
            "General Purpose Ddsv5 Series Compute"
        ),
        "meterName": "1 vCore",
        "skuName": "1 vCore",
        "retailPrice": 0.089,
    }
    item = _pg_lookup_retail_price(
        vendor=Mock(),
        database_id="Standard_D16ds_v5",
        edition_name="Ddsv5",
        prices_by_arm={
            "Standard_D16ds_v5": [full_sku],
            "1 vCore": [ddsv5_per_vcore],
        },
    )
    assert item is full_sku


def test_pg_hourly_compute_price_burstable_meter_is_full_instance():
    """Retail 'B2ms vCore' is the whole SKU hour, not a per-vCore rate."""
    item = {
        "armSkuName": "Standard_B2ms",
        "meterName": "B2ms vCore",
        "skuName": "B2ms",
        "retailPrice": 0.136,
    }
    assert _pg_hourly_compute_price(item, 2, database_id="Standard_B2ms") == 0.136

    sized = {
        "armSkuName": "AzureDB_PostgreSQL_Flexible_Server_Memory_Optimized_Esv3Series_Compute",
        "meterName": "vCore",
        "skuName": "16 vCore",
        "retailPrice": 1.8896,
    }
    assert _pg_hourly_compute_price(sized, 16, database_id="Standard_E16s_v3") == 1.8896

    per_core = {
        "armSkuName": "AzureDB_PostgreSQL_Flexible_Server_Memory_Optimized_Esv3Series_Compute",
        "meterName": "vCore",
        "skuName": "vCore",
        "retailPrice": 0.1181,
    }
    assert (
        _pg_hourly_compute_price(per_core, 16, database_id="Standard_E16s_v3") == 1.8896
    )

    # Dsv6 publishes the per-vCore meter as arm `..._Series_Compute_1_vCore`.
    series_one = {
        "armSkuName": (
            "Azure_Database_for_PostgreSQL_Flexible_Server_"
            "General_Purpose_Dsv6_Series_Compute_1_vCore"
        ),
        "meterName": "1 vCore",
        "skuName": "1 vCore",
        "retailPrice": 0.089,
    }
    assert (
        _pg_hourly_compute_price(series_one, 2, database_id="Standard_D2s_v6") == 0.178
    )
    full_size_arm = {
        "armSkuName": (
            "Azure_Database_for_PostgreSQL_Flexible_Server_"
            "Memory_Purpose_Eadsv5_Series_Compute_16_vCore"
        ),
        "meterName": "vCore",
        "skuName": "16 vCore",
        "retailPrice": 2.0,
    }
    assert (
        _pg_hourly_compute_price(full_size_arm, 16, database_id="Standard_E16ads_v5")
        == 2.0
    )


def test_pg_storage_prices_skip_unsupported_retail_meters():
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="centralus", api_reference="centralus")]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    ultra_disk_retail = {
        "productName": "Azure Database for PostgreSQL Flex Server Storage",
        "meterName": "Ultra Disk Storage Data Stored",
        "unitOfMeasure": "1 GB/Month",
        "retailPrice": "0.25",
        "currencyCode": "USD",
    }
    managed_disk_retail = {
        "productName": "Azure Database for PostgreSQL Flex Server Storage",
        "meterName": "Storage Data Stored",
        "unitOfMeasure": "1 GB/Month",
        "retailPrice": "0.115",
        "currencyCode": "USD",
    }
    managed_disk_v2_retail = {
        "productName": "Az DB for PostgreSQL Flexible Server Storage",
        "meterName": "Premium SSD v2 Storage Data Stored",
        "unitOfMeasure": "1 GB/Month",
        "retailPrice": "0.131",
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
                        name="ManagedDiskV2",
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
            return_value=[
                ultra_disk_retail,
                managed_disk_retail,
                managed_disk_v2_retail,
                backup_retail,
            ],
        ),
    ):
        prices = azure_database_storage_prices(vendor)
    storage_ids = {row["database_storage_id"] for row in prices}
    assert storage_ids == {"ManagedDisk", "ManagedDiskV2", "BackupStorageLRS"}


def test_parse_database_name_series():
    assert _parse_database_name("Standard_B1ms")[0] == "Bs"
    assert _parse_database_name("B1ms")[0] == "Bs"
    assert _parse_database_name("Standard_B2s") == ("Bs", "B", 2, None)
    assert _parse_database_name("Standard_D16ds_v6") == ("Ddsv6", "D", 16, "6")
    assert _parse_database_name("Standard_D16s_v6")[0] == "Dsv6"
    assert _parse_database_name("Standard_D16ads_v5")[0] == "Dadsv5"
    assert _parse_database_name("Standard_DC16ads_v6")[0] == "DCadsv6"
    assert _parse_database_name("Standard_DC2es_v6")[0] == "DCesv6"
    assert _parse_database_name("Standard_E192ids_v6")[0] == "Edsv6"
    assert _parse_database_name("Standard_EC4as_v5")[0] == "ECasv5"
    assert _parse_database_name("Standard_D16ps_v") == ("Dps", "D", 16, "")


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


def test_gcp_machine_type_status_from_deprecation_state():
    # https://cloud.google.com/compute/docs/reference/rest/v1/machineTypes
    assert _gcp_machine_type_status("") == Status.ACTIVE
    assert _gcp_machine_type_status("ACTIVE") == Status.ACTIVE
    assert _gcp_machine_type_status(None) == Status.ACTIVE
    assert _gcp_machine_type_status("DEPRECATED") == Status.PLANNED_FOR_RETIREMENT
    assert _gcp_machine_type_status("OBSOLETE") == Status.RETIRED
    assert _gcp_machine_type_status("DELETED") == Status.RETIRED


def test_gcp_inventory_databases_inherits_gce_machine_type_status():
    vendor = Mock(vendor_id="gcp")
    vendor.regions = []
    vendor.servers = [
        Mock(
            server_id="n1-standard-4",
            api_reference="n1-standard-4",
            status=Status.PLANNED_FOR_RETIREMENT,
        )
    ]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    with (
        patch(
            "sc_crawler.vendors._gcp._pg_sqladmin_metadata",
            return_value={
                "tiers": [
                    {
                        "tier": "db-n1-standard-4",
                        "RAM": "16106127360",
                        "region": ["us-central1"],
                    },
                    {
                        "tier": "db-perf-optimized-N-4",
                        "RAM": "17179869184",
                        "region": ["us-central1"],
                    },
                ],
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
    assert by_id["db-n1-standard-4"]["status"] == Status.PLANNED_FOR_RETIREMENT
    # no matching GCE machine type
    assert by_id["db-perf-optimized-N-4"]["status"] == Status.ACTIVE


def test_gcp_inventory_databases_ha_uses_own_price_family_only():
    vendor = Mock(vendor_id="gcp")
    vendor.regions = []
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    tiers = [
        {
            "tier": "db-n1-standard-4",
            "RAM": "16106127360",
            "region": ["us-central1"],
        },
        {
            "tier": "db-perf-optimized-N-4",
            "RAM": "17179869184",
            "region": ["us-central1"],
        },
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
            # Only Enterprise Plus regional HA meters — must not imply Enterprise HA.
            return_value=({}, frozenset({("us-central1", "enterprise_plus")})),
        ),
    ):
        rows = inventory_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert by_id["db-n1-standard-4"]["ha"] == [DatabaseHaLevel.NONE]
    assert by_id["db-n1-standard-4"]["sla"] is None
    assert by_id["db-n1-standard-4"]["api_reference_object"] == {
        "settings": {"tier": "db-n1-standard-4"}
    }
    assert by_id["db-perf-optimized-N-4"]["ha"] == [
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.NONE,
    ]
    assert by_id["db-perf-optimized-N-4"]["sla"] == 99.99


def test_gcp_inventory_databases_ha_multi_zone_from_regional_billing():
    vendor = Mock(vendor_id="gcp")
    vendor.regions = []
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    tiers = [
        {
            "tier": "db-perf-optimized-N-4",
            "RAM": "17179869184",
            "region": ["us-central1"],
        },
        {
            "tier": "db-n1-standard-4",
            "RAM": "16106127360",
            "region": ["us-central1"],
        },
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
            return_value=(
                {},
                frozenset(
                    {
                        ("us-central1", "enterprise"),
                        ("us-central1", "enterprise_plus"),
                        ("us-central1", "shared"),
                    }
                ),
            ),
        ),
    ):
        rows = inventory_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert by_id["db-n1-standard-4"]["ha"] == [
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.NONE,
    ]
    assert by_id["db-n1-standard-4"]["ha_strategy"] == [
        DatabaseHaStrategy.PASSIVE_STANDBY,
        DatabaseHaStrategy.NONE,
    ]
    assert by_id["db-n1-standard-4"]["sla"] == 99.95
    assert by_id["db-perf-optimized-N-4"]["ha"] == [
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.NONE,
    ]
    assert by_id["db-perf-optimized-N-4"]["ha_strategy"] == [
        DatabaseHaStrategy.PASSIVE_STANDBY,
        DatabaseHaStrategy.NONE,
    ]
    assert by_id["db-perf-optimized-N-4"]["sla"] == 99.99
    assert by_id["db-perf-optimized-N-4"]["security_features"] == [
        DatabaseSecurityFeature.IP_FILTERING,
        DatabaseSecurityFeature.PRIVATE_NETWORK,
        DatabaseSecurityFeature.NETWORK_PEERING,
        DatabaseSecurityFeature.IDENTITY_BASED_AUTH,
        DatabaseSecurityFeature.CLIENT_CERT_AUTH,
        DatabaseSecurityFeature.ENFORCED_TLS,
        DatabaseSecurityFeature.CUSTOMER_MANAGED_KEYS,
        DatabaseSecurityFeature.AUDIT_LOGGING,
    ]
    assert by_id["db-n1-standard-4"]["sla"] == 99.95
    assert by_id["db-f1-micro"]["ha"] == [
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.NONE,
    ]
    assert by_id["db-f1-micro"]["sla"] is None


def test_gcp_inventory_databases_filters_engine_versions_by_edition():
    vendor = Mock(vendor_id="gcp")
    vendor.regions = []
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    tiers = [
        {
            "tier": "db-f1-micro",
            "RAM": "644245094",
            "region": ["us-central1"],
        },
        {
            "tier": "db-perf-optimized-N-8",
            "RAM": str(64 * 1024**3),
            "region": ["us-central1"],
        },
        {
            "tier": "db-perf-optimized-C4-2",
            "RAM": str(15 * 1024**3),
            "region": ["us-central1"],
        },
        {
            "tier": "db-c4a-highmem-4",
            "RAM": str(32 * 1024**3),
            "region": ["us-central1"],
        },
    ]
    with (
        patch(
            "sc_crawler.vendors._gcp._pg_sqladmin_metadata",
            return_value={
                "tiers": tiers,
                # flags.list can advertise unreleased majors; create-instance rejects 19.
                "engine_versions": [
                    "9.6",
                    "10",
                    "11",
                    "12",
                    "13",
                    "14",
                    "15",
                    "16",
                    "17",
                    "18",
                    "19",
                ],
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
    assert by_id["db-f1-micro"]["engine_versions"] == [
        "9.6",
        "10",
        "11",
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
    ]
    assert by_id["db-perf-optimized-N-8"]["engine_versions"] == [
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
    ]
    # only C4A drops PostgreSQL 12
    assert by_id["db-perf-optimized-C4-2"]["engine_versions"] == [
        "12",
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
    ]
    assert by_id["db-c4a-highmem-4"]["engine_versions"] == [
        "13",
        "14",
        "15",
        "16",
        "17",
        "18",
    ]


def test_gcp_compute_sku_class():
    assert _pg_compute_sku_class(
        "Cloud SQL for PostgreSQL: Zonal - Enterprise Plus N vCPU in Iowa"
    ) == ("enterprise_plus", "vcpu")
    assert _pg_compute_sku_class(
        "Cloud SQL for PostgreSQL: Zonal - Enterprise Plus N RAM in Iowa"
    ) == ("enterprise_plus", "ram")
    assert _pg_compute_sku_class(
        "Cloud SQL for Postgres: Zonal - Enterprise Plus Performance Optimized C4A vCPU in Iowa"
    ) == ("enterprise_plus_c4a", "vcpu")
    assert _pg_compute_sku_class(
        "Cloud SQL for PostgreSQL: Zonal - Enterprise Plus C4A RAM in Iowa"
    ) == ("enterprise_plus_c4a", "ram")
    assert _pg_compute_sku_class(
        "Cloud SQL for PostgreSQL: Zonal - Enterprise Plus C4 vCPU in Johannesburg"
    ) == ("enterprise_plus_c4", "vcpu")
    assert _pg_compute_sku_class(
        "Cloud SQL for PostgreSQL: Regional - Enterprise Plus C4 RAM in Johannesburg"
    ) == ("enterprise_plus_c4", "ram")
    assert _pg_compute_sku_class(
        "Cloud SQL for Postgres: Zonal - Enterprise N4 vCPU in Iowa"
    ) == ("enterprise_n4", "vcpu")
    assert _pg_compute_sku_class(
        "Cloud SQL for PostgreSQL: Zonal - vCPU in Americas"
    ) == ("enterprise", "vcpu")
    assert (
        _pg_compute_sku_class(
            "FDC Trial in Cloud SQL for PostgreSQL: Zonal - vCPU in Mexico"
        )
        is None
    )


def test_gcp_inventory_databases_enterprise_plus_without_regional_ha():
    vendor = Mock(vendor_id="gcp")
    vendor.regions = []
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    tiers = [
        {
            "tier": "db-perf-optimized-N-4",
            "RAM": "17179869184",
            "region": ["us-central1"],
        },
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
    assert rows[0]["ha"] == [DatabaseHaLevel.NONE]
    assert rows[0]["sla"] is None


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
    assert prices[0]["ha"] == DatabaseHaLevel.NONE
    assert prices[0]["ha_strategy"] == DatabaseHaStrategy.NONE
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
    assert prices[0]["ha"] == DatabaseHaLevel.NONE
    assert prices[0]["ha_strategy"] == DatabaseHaStrategy.NONE


def test_gcp_enterprise_plus_prices_use_plus_meters_not_enterprise_n4():
    # Plus N: 0.0537 * 4 + 0.0091 * 32 = 0.506
    # Plus C4 / C4A: 0.054 * 4 + 0.009 * 32 = 0.504
    skus = [
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Zonal - Enterprise Plus N vCPU in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=53_700_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Zonal - Enterprise Plus N RAM in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=9_100_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Regional - Enterprise Plus N vCPU in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=107_400_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Regional - Enterprise Plus N RAM in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=18_200_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for Postgres: Zonal - Enterprise Plus Performance Optimized C4A vCPU in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=54_000_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Zonal - Enterprise Plus C4A RAM in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=9_000_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for Postgres: Regional - Enterprise Plus Performance Optimized C4A vCPU in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=108_000_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Regional - Enterprise Plus C4A RAM in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=18_000_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Zonal - Enterprise Plus C4 vCPU in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=54_000_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Zonal - Enterprise Plus C4 RAM in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=9_000_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Regional - Enterprise Plus C4 vCPU in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=108_000_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Regional - Enterprise Plus C4 RAM in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=18_000_000,
        ),
        # Wrong meter for Plus tiers — must not be selected.
        _gcp_pg_sku(
            "Cloud SQL for Postgres: Zonal - Enterprise N4 vCPU in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=41_300_000,
        ),
    ]
    vendor = Mock(vendor_id="gcp")
    vendor.regions = [Mock(region_id="1", api_reference="us-central1")]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    tiers = [
        {
            "tier": "db-c4a-highmem-4",
            "RAM": str(32 * 1024**3),
            "region": ["us-central1"],
        },
        {
            "tier": "db-perf-optimized-N-4",
            "RAM": str(32 * 1024**3),
            "region": ["us-central1"],
        },
        {
            "tier": "db-memory-optimized-N-4",
            "RAM": str(32 * 1024**3),
            "region": ["us-central1"],
        },
        {
            "tier": "db-perf-optimized-C4-4",
            "RAM": str(32 * 1024**3),
            "region": ["us-central1"],
        },
    ]
    with (
        patch("sc_crawler.vendors._gcp._cloud_sql_skus", return_value=skus),
        patch(
            "sc_crawler.vendors._gcp._pg_sqladmin_metadata",
            return_value={"tiers": tiers},
        ),
    ):
        prices = inventory_database_prices(vendor)
    by_id_ha = {(row["database_id"], row["ha"]): row for row in prices}
    for database_id in ("db-perf-optimized-N-4", "db-memory-optimized-N-4"):
        zonal = by_id_ha[(database_id, DatabaseHaLevel.NONE)]
        regional = by_id_ha[(database_id, DatabaseHaLevel.MULTI_ZONE)]
        assert abs(zonal["price"] - 0.506) < 0.001
        assert abs(regional["price"] - 1.012) < 0.001
        assert regional["ha_strategy"] == DatabaseHaStrategy.PASSIVE_STANDBY
    c4a_zonal = by_id_ha[("db-c4a-highmem-4", DatabaseHaLevel.NONE)]
    c4a_regional = by_id_ha[("db-c4a-highmem-4", DatabaseHaLevel.MULTI_ZONE)]
    assert abs(c4a_zonal["price"] - 0.504) < 0.001
    assert abs(c4a_regional["price"] - 1.008) < 0.001
    c4_zonal = by_id_ha[("db-perf-optimized-C4-4", DatabaseHaLevel.NONE)]
    c4_regional = by_id_ha[("db-perf-optimized-C4-4", DatabaseHaLevel.MULTI_ZONE)]
    assert abs(c4_zonal["price"] - 0.504) < 0.001
    assert abs(c4_regional["price"] - 1.008) < 0.001


def test_gcp_inventory_skips_custom_tiers():
    vendor = Mock(vendor_id="gcp")
    vendor.regions = [Mock(region_id="1", api_reference="us-central1")]
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    tiers = [
        {
            "tier": "db-custom-N4-4-32768",
            "RAM": str(32 * 1024**3),
            "region": ["us-central1"],
        },
        {
            "tier": "db-custom-4-16384",
            "RAM": str(16 * 1024**3),
            "region": ["us-central1"],
        },
        {
            "tier": "db-n1-standard-4",
            "RAM": str(15 * 1024**3),
            "region": ["us-central1"],
        },
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
        patch("sc_crawler.vendors._gcp._cloud_sql_skus", return_value=[]),
    ):
        databases = inventory_databases(vendor)
        prices = inventory_database_prices(vendor)
    assert [row["database_id"] for row in databases] == ["db-n1-standard-4"]
    assert prices == []


def test_gcp_database_prices_emit_regional_ha_rows():
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
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Regional - vCPU in Americas",
            regions=["us-central1"],
            units=0,
            nanos=82_600_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Regional - RAM in Americas",
            regions=["us-central1"],
            units=0,
            nanos=14_000_000,
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
    by_ha = {(row["ha"], row["ha_strategy"]): row for row in prices}
    assert set(by_ha) == {
        (DatabaseHaLevel.NONE, DatabaseHaStrategy.NONE),
        (DatabaseHaLevel.MULTI_ZONE, DatabaseHaStrategy.PASSIVE_STANDBY),
    }
    assert (
        abs(by_ha[(DatabaseHaLevel.NONE, DatabaseHaStrategy.NONE)]["price"] - 0.2702)
        < 0.001
    )
    assert (
        abs(
            by_ha[(DatabaseHaLevel.MULTI_ZONE, DatabaseHaStrategy.PASSIVE_STANDBY)][
                "price"
            ]
            - 0.5404
        )
        < 0.001
    )
