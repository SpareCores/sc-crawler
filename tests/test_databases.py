from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sc_crawler.table_fields import (
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
    _describe_orderable_db_instance_options_for_class_with_progress,
    _extract_rds_bundled_storage_size,
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
from sc_crawler.vendors._aws import (
    _reconcile_server_status as aws_reconcile_server_status,
)
from sc_crawler.vendors._aws import (
    inventory_server_prices as aws_server_prices,
)
from sc_crawler.vendors._azure import (
    _azure_sku_lifecycle_status,
    _pg_database_regions,
    _pg_engine_versions,
    _pg_lookup_retail_price,
)
from sc_crawler.vendors._azure import (
    inventory_database_prices as azure_database_prices,
)
from sc_crawler.vendors._azure import (
    inventory_database_storage_prices as azure_database_storage_prices,
)
from sc_crawler.vendors._azure import (
    inventory_databases as azure_databases,
)
from sc_crawler.vendors._gcp import (
    _gcp_machine_type_status,
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


def test_azure_sku_lifecycle_status_from_retired_sizes_list():
    # https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/lifecycle/retired-sizes-list
    announced = [
        "Standard_D2",
        "Standard_DS2",
        "Standard_D2_v2",
        "Standard_DS2_v2",
        "Standard_A2_v2",
        "Standard_A2m_v2",
        "Standard_B1ms",
        "Standard_F2",
        "Standard_F2s",
        "Standard_F2s_v2",
        "Standard_G1",
        "Standard_GS2",
        "Standard_L8s",
        "Standard_L8s_v2",
        "Standard_NV12s_v3",
        "Standard_NV8as_v4",
        "Standard_NV8ahs_v4",
        "Standard_NP10s",
        "Standard_HC44rs",
        "Standard_HC44-16rs",
        "Standard_M192ims_v2",
        "Standard_M192ids_v2",
    ]
    retired = [
        "Standard_A2",
        "Standard_NC6",
        "Standard_NC24r",
        "Standard_NC12s_v2",
        "Standard_ND6",
        "Standard_ND24r",
        "Standard_DC2s_v2",
        "Standard_NC6s_v3",
        "Standard_NC24rs_v3",
    ]
    active = [
        "Standard_D2s_v3",
        "Standard_D4s_v5",
        "Standard_B2als_v2",
        "Standard_E2s_v3",
        "Standard_L8s_v3",
        "Standard_NC4as_T4_v3",
        "Standard_NV4ads_V710_v5",
        "Standard_M64s_v2",
    ]
    as_of = date(2026, 8, 19)
    for sku in announced:
        assert (
            _azure_sku_lifecycle_status(sku, as_of=as_of)
            == Status.PLANNED_FOR_RETIREMENT
        ), sku
    for sku in retired:
        assert _azure_sku_lifecycle_status(sku, as_of=as_of) == Status.RETIRED, sku
    for sku in active:
        assert _azure_sku_lifecycle_status(sku, as_of=as_of) == Status.ACTIVE, sku


def test_azure_sku_lifecycle_status_transitions_on_retirement_date():
    # NVv3: retires 2026-09-30
    assert (
        _azure_sku_lifecycle_status("Standard_NV12s_v3", as_of=date(2026, 9, 29))
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert (
        _azure_sku_lifecycle_status("Standard_NV12s_v3", as_of=date(2026, 9, 30))
        == Status.RETIRED
    )
    # D-series: retires 2028-05-01
    assert (
        _azure_sku_lifecycle_status("Standard_D2", as_of=date(2028, 4, 30))
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert (
        _azure_sku_lifecycle_status("Standard_D2", as_of=date(2028, 5, 1))
        == Status.RETIRED
    )
    # NVv4 (as_v4): retires 2026-09-30
    assert (
        _azure_sku_lifecycle_status("Standard_NV8as_v4", as_of=date(2026, 9, 29))
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert (
        _azure_sku_lifecycle_status("Standard_NV8as_v4", as_of=date(2026, 9, 30))
        == Status.RETIRED
    )
    # NVv4 (ahs_v4): retires 2026-09-30
    assert (
        _azure_sku_lifecycle_status("Standard_NV8ahs_v4", as_of=date(2026, 9, 29))
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert (
        _azure_sku_lifecycle_status("Standard_NV8ahs_v4", as_of=date(2026, 9, 30))
        == Status.RETIRED
    )
    # NP-series: retires 2027-05-31
    assert (
        _azure_sku_lifecycle_status("Standard_NP10s", as_of=date(2027, 5, 30))
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert (
        _azure_sku_lifecycle_status("Standard_NP10s", as_of=date(2027, 5, 31))
        == Status.RETIRED
    )


def test_azure_inventory_databases_autotuning_from_supported_features():
    """IndexTuning → advice; AdaptiveAutoVacuumAutoApply → apply (param auto-tune)."""
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="centralus", api_reference="centralus")]
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )

    def _sku(name, v_cores=2):
        return SimpleNamespace(
            name=name,
            v_cores=v_cores,
            supported_memory_per_vcore_mb=4096,
            supported_ha_mode=[],
        )

    capability = SimpleNamespace(
        supported_server_versions=[SimpleNamespace(name="16", status="Available")],
        storage_auto_growth_supported=None,
        supported_features=[
            SimpleNamespace(name="IndexTuning", status="Enabled"),
            SimpleNamespace(name="AdaptiveAutoVacuumAutoApply", status="Enabled"),
        ],
        supported_server_editions=[
            SimpleNamespace(
                name="GeneralPurpose",
                supported_storage_editions=[],
                supported_server_skus=[_sku("Standard_D2s_v3")],
            )
        ],
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
    ):
        rows = azure_databases(vendor)
    assert rows[0]["autotuning_advice"] is True
    assert rows[0]["autotuning_apply"] is True

    capability.supported_features = [
        SimpleNamespace(name="IndexTuning", status="Enabled"),
        SimpleNamespace(name="AdaptiveAutoVacuumAutoApply", status="Disabled"),
    ]
    with (
        patch(
            "sc_crawler.vendors._azure._pg_database_regions",
            return_value=vendor.regions,
        ),
        patch(
            "sc_crawler.vendors._azure._pg_capabilities",
            return_value=[capability],
        ),
    ):
        rows = azure_databases(vendor)
    assert rows[0]["autotuning_advice"] is True
    assert rows[0]["autotuning_apply"] is False


def test_azure_inventory_databases_ha_from_supported_ha_mode():
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="centralus", api_reference="centralus")]
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    capability = SimpleNamespace(
        supported_server_versions=[
            SimpleNamespace(name="16", status="Available"),
        ],
        storage_auto_growth_supported="Enabled",
        supported_features=[],
        supported_server_editions=[
            SimpleNamespace(
                name="Burstable",
                supported_storage_editions=[],
                supported_server_skus=[
                    SimpleNamespace(
                        name="Standard_B1ms",
                        v_cores=1,
                        supported_memory_per_vcore_mb=2048,
                        supported_ha_mode=["SameZone", "ZoneRedundant"],
                    )
                ],
            ),
            SimpleNamespace(
                name="GeneralPurpose",
                supported_storage_editions=[],
                supported_server_skus=[
                    SimpleNamespace(
                        name="Standard_D2s_v3",
                        v_cores=2,
                        supported_memory_per_vcore_mb=4096,
                        supported_ha_mode=["SameZone", "ZoneRedundant"],
                    ),
                    SimpleNamespace(
                        name="Standard_D4s_v3",
                        v_cores=4,
                        supported_memory_per_vcore_mb=4096,
                        supported_ha_mode=["SameZone"],
                    ),
                ],
            ),
            SimpleNamespace(
                name="MemoryOptimized",
                supported_storage_editions=[],
                supported_server_skus=[
                    SimpleNamespace(
                        name="Standard_E2s_v3",
                        v_cores=2,
                        supported_memory_per_vcore_mb=8192,
                        supported_ha_mode=["ZoneRedundant"],
                    )
                ],
            ),
        ],
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
    ):
        rows = azure_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert by_id["Standard_B1ms"]["ha"] == [DatabaseHaLevel.NONE]
    assert by_id["Standard_B1ms"]["ha_strategy"] == [DatabaseHaStrategy.NONE]
    assert by_id["Standard_B1ms"]["sla"] == 99.9
    assert by_id["Standard_B1ms"]["scheduled_backups"] is True
    assert by_id["Standard_B1ms"]["security_features"] == [
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
        not in by_id["Standard_B1ms"]["security_features"]
    )
    assert by_id["Standard_D2s_v3"]["ha"] == [
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.SINGLE_ZONE,
        DatabaseHaLevel.NONE,
    ]
    assert by_id["Standard_D2s_v3"]["ha_strategy"] == [
        DatabaseHaStrategy.PASSIVE_STANDBY,
        DatabaseHaStrategy.NONE,
    ]
    assert by_id["Standard_D2s_v3"]["sla"] == 99.99
    assert by_id["Standard_D2s_v3"]["api_reference_object"] == {
        "sku_name": "GP_Standard_D2s_v3"
    }
    assert by_id["Standard_D4s_v3"]["ha"] == [
        DatabaseHaLevel.SINGLE_ZONE,
        DatabaseHaLevel.NONE,
    ]
    assert by_id["Standard_D4s_v3"]["ha_strategy"] == [
        DatabaseHaStrategy.PASSIVE_STANDBY,
        DatabaseHaStrategy.NONE,
    ]
    assert by_id["Standard_D4s_v3"]["sla"] == 99.95
    assert by_id["Standard_E2s_v3"]["ha"] == [
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.NONE,
    ]
    assert by_id["Standard_E2s_v3"]["ha_strategy"] == [
        DatabaseHaStrategy.PASSIVE_STANDBY,
        DatabaseHaStrategy.NONE,
    ]
    assert by_id["Standard_B1ms"]["status"] == Status.PLANNED_FOR_RETIREMENT
    assert by_id["Standard_D2s_v3"]["status"] == Status.ACTIVE
    assert by_id["Standard_E2s_v3"]["status"] == Status.ACTIVE


def test_azure_inventory_database_prices_emit_ha_rows():
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="centralus", api_reference="centralus")]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    capability = SimpleNamespace(
        supported_server_editions=[
            SimpleNamespace(
                name="Burstable",
                supported_server_skus=[
                    SimpleNamespace(
                        name="Standard_B1ms",
                        v_cores=1,
                        supported_ha_mode=["SameZone", "ZoneRedundant"],
                    )
                ],
            ),
            SimpleNamespace(
                name="GeneralPurpose",
                supported_server_skus=[
                    SimpleNamespace(
                        name="Standard_D2s_v3",
                        v_cores=2,
                        supported_ha_mode=["SameZone", "ZoneRedundant"],
                    )
                ],
            ),
        ],
    )
    retail = [
        {
            "armSkuName": "B1MS",
            "productName": (
                "Azure Database for PostgreSQL Flexible Server "
                "Burstable BS Series Compute"
            ),
            "meterName": "B1MS",
            "retailPrice": "0.018",
            "currencyCode": "USD",
        },
        {
            "armSkuName": "Standard_D2s_v3",
            "productName": (
                "Azure Database for PostgreSQL Flexible Server "
                "General Purpose Dsv3 Series Compute"
            ),
            "meterName": "D2s v3",
            "skuName": "2 vCore",
            "retailPrice": "0.145",
            "currencyCode": "USD",
        },
    ]
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
            return_value=retail,
        ),
    ):
        prices = azure_database_prices(vendor)
    by_key = {
        (row["database_id"], row["ha"], row["ha_strategy"]): row["price"]
        for row in prices
    }
    assert (
        by_key[
            (
                "Standard_B1ms",
                DatabaseHaLevel.NONE,
                DatabaseHaStrategy.NONE,
            )
        ]
        == 0.018
    )
    assert (
        "Standard_B1ms",
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaStrategy.PASSIVE_STANDBY,
    ) not in by_key
    assert (
        by_key[
            (
                "Standard_D2s_v3",
                DatabaseHaLevel.NONE,
                DatabaseHaStrategy.NONE,
            )
        ]
        == 0.145
    )
    assert (
        by_key[
            (
                "Standard_D2s_v3",
                DatabaseHaLevel.MULTI_ZONE,
                DatabaseHaStrategy.PASSIVE_STANDBY,
            )
        ]
        == 0.29
    )
    assert (
        by_key[
            (
                "Standard_D2s_v3",
                DatabaseHaLevel.SINGLE_ZONE,
                DatabaseHaStrategy.PASSIVE_STANDBY,
            )
        ]
        == 0.29
    )


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
            return_value=({}, frozenset({("us-central1", "enterprise_n4")})),
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
                        ("us-central1", "enterprise_n4"),
                        ("us-central1", "shared"),
                    }
                ),
            ),
        ),
    ):
        rows = inventory_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
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
    assert by_id["db-n1-standard-4"]["ha"] == [
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.NONE,
    ]
    assert by_id["db-n1-standard-4"]["sla"] == 99.95
    assert by_id["db-f1-micro"]["ha"] == [
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.NONE,
    ]
    assert by_id["db-f1-micro"]["sla"] is None


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


def test_gcp_n4_family_prices_fall_back_to_enterprise_ram():
    # Enterprise N4 vCPU + generic PostgreSQL RAM (no Enterprise N4 RAM SKU).
    # 0.0542 * 4 + 0.0091 * 32 = 0.508
    skus = [
        _gcp_pg_sku(
            "Cloud SQL for Postgres: Zonal - Enterprise N4 vCPU in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=54_200_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Zonal - RAM in Americas",
            regions=["us-central1"],
            units=0,
            nanos=9_100_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for Postgres: Regional - Enterprise N4 vCPU in Iowa",
            regions=["us-central1"],
            units=0,
            nanos=108_400_000,
        ),
        _gcp_pg_sku(
            "Cloud SQL for PostgreSQL: Regional - RAM in Americas",
            regions=["us-central1"],
            units=0,
            nanos=18_200_000,
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
    for database_id in (
        "db-c4a-highmem-4",
        "db-perf-optimized-N-4",
        "db-memory-optimized-N-4",
    ):
        zonal = by_id_ha[(database_id, DatabaseHaLevel.NONE)]
        regional = by_id_ha[(database_id, DatabaseHaLevel.MULTI_ZONE)]
        assert abs(zonal["price"] - 0.508) < 0.001
        assert abs(regional["price"] - 1.016) < 0.001
        assert regional["ha_strategy"] == DatabaseHaStrategy.PASSIVE_STANDBY


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
    m5 = Mock(server_id="m5.large", status=Status.ACTIVE)
    t1 = Mock(server_id="t1.micro", status=Status.ACTIVE)
    mac = Mock(server_id="mac1.metal", status=Status.ACTIVE)
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


def test_aws_reconcile_server_status_keeps_spot_only_instance_types_active():
    region = Mock(
        region_id="us-east-1",
        api_reference="us-east-1",
        aliases=[],
        status=Status.ACTIVE,
    )
    region.name = "US East (N. Virginia)"
    spot_only = Mock(server_id="p4d.24xlarge", status=Status.INACTIVE)
    vendor = _aws_vendor(regions=[region], servers=[spot_only])
    with patch(
        "sc_crawler.vendors._aws._describe_instance_type_offerings_per_zone_with_progress",
        return_value={},
    ):
        aws_reconcile_server_status(vendor, spot_server_ids={"p4d.24xlarge"})
    assert spot_only.status == Status.ACTIVE


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
