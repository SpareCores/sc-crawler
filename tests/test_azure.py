from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from sc_crawler.table_fields import (
    DatabaseHaLevel,
    DatabaseHaStrategy,
    DatabaseSecurityFeature,
    Status,
)
from sc_crawler.vendors._azure import (
    _PG_PRODUCT_SERIES_RE,
    _azure_sku_lifecycle_status,
    _compatible_storage_ids,
    _disk_sku_names,
    _parse_database_name,
    _pg_database_regions,
    _pg_edition_family,
    _pg_engine_versions,
    _pg_hourly_compute_price,
    _pg_lookup_retail_price,
    _standardize_server,
    _storage_meter_mapping,
    _ultra_disk_vm_sizes,
    _vm_family_category,
    _vm_retirement_dates,
    _vm_series,
    _warn_unknown_disk,
    inventory_storage_prices,
    inventory_storages,
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


@pytest.fixture(autouse=True)
def _no_api_retirement_dates():
    """Keep the tests offline: no retirement dates from the Compute API."""
    with patch("sc_crawler.vendors._azure._vm_retirement_dates", return_value={}):
        yield


@pytest.fixture(autouse=True)
def _no_compute_api_disks():
    """Keep the tests offline: fixed disk types and no Ultra capable sizes."""
    with (
        patch(
            "sc_crawler.vendors._azure._disk_sku_names",
            return_value=["Premium_LRS", "Standard_LRS", "UltraSSD_LRS"],
        ),
        patch(
            "sc_crawler.vendors._azure._ultra_disk_vm_sizes",
            return_value=frozenset(),
        ),
    ):
        yield


@pytest.mark.parametrize(
    ("server_name", "family"),
    [
        ("Standard_D2s_v3", "General Purpose"),
        ("Standard_DC16as_v5", "General Purpose"),
        ("Standard_DS3_v2", "General Purpose"),
        ("Standard_B2ms", "General Purpose"),
        ("Standard_A4_v2", "General Purpose"),
        # no documentation lists A8-A11 other than the (general purpose) A family
        ("Standard_A8", "General Purpose"),
        ("Standard_F16s_v2", "Compute Optimized"),
        ("Standard_FX12mds", "Compute Optimized"),
        ("Standard_E32as_v6", "Memory Optimized"),
        ("Standard_EC64es_v6", "Memory Optimized"),
        ("Standard_M128s", "Memory Optimized"),
        # previous generation memory optimized sizes
        ("Standard_G1", "Memory Optimized"),
        ("Standard_GS5-16", "Memory Optimized"),
        # D11-D15 and DS11-DS15 are memory optimized, other D sizes are not
        ("Standard_D11", "Memory Optimized"),
        ("Standard_D15_v2", "Memory Optimized"),
        ("Standard_DS11-1_v2", "Memory Optimized"),
        ("Standard_DS14_v2", "Memory Optimized"),
        ("Standard_D16_v3", "General Purpose"),
        ("Standard_D1", "General Purpose"),
        ("Standard_L8s_v3", "Storage Optimized"),
        ("Standard_NC24ads_A100_v4", "GPU Accelerated"),
        ("Standard_NCC40ads_H100_v5", "GPU Accelerated"),
        ("Standard_ND96isr_H100_v5", "GPU Accelerated"),
        ("Standard_NV36ads_A10_v5", "GPU Accelerated"),
        ("Standard_NP10s", "FPGA Accelerated"),
        ("Standard_HB120rs_v3", "High Performance Computing"),
        # retired H-series
        ("Standard_H16r", "High Performance Computing"),
        # not documented by Microsoft, and unknown families are not guessed
        ("Standard_PB6s", None),
        ("Standard_ZZ4s_v1", None),
    ],
)
def test_azure_vm_family_category(server_name, family):
    assert _vm_family_category(server_name) == family


def test_azure_standardize_server_family_and_series():
    server = {
        "name": "Standard_NC4as_T4_v3",
        # the SKU family has spaces around the accelerator for some SKUs
        "family": "standard NCASv3_T4 Family",
        "capabilities": [
            {"name": "CpuArchitectureType", "value": "x64"},
            {"name": "vCPUs", "value": "4"},
            {"name": "vCPUsAvailable", "value": "4"},
            {"name": "MemoryGB", "value": "28"},
        ],
    }
    row = _standardize_server(server, SimpleNamespace(vendor_id="azure"))
    assert row["family"] == "GPU Accelerated"
    assert row["series"] == "NCASv3_T4"


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
        "Standard_HB120rs_v2",
        "Standard_M192ims_v2",
        "Standard_M192ids_v2",
        "Standard_DC2s_v3",
        "Standard_DC8ds_v3",
        "Standard_DC4as_cc_v5",
        "Standard_DC8ads_cc_v5",
        "Standard_EC4as_cc_v5",
        "Standard_EC4ads_cc_v5",
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
        "Standard_E4s_v3",
        "Standard_DC4as_v5",
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
    # DCas_cc_v5 / ECas_cc_v5: retires 2026-09-01
    assert (
        _azure_sku_lifecycle_status("Standard_DC4as_cc_v5", as_of=date(2026, 8, 31))
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert (
        _azure_sku_lifecycle_status("Standard_DC4as_cc_v5", as_of=date(2026, 9, 1))
        == Status.RETIRED
    )
    # DCsv3 / DCdsv3: retires 2029-10-31
    assert (
        _azure_sku_lifecycle_status("Standard_DC2s_v3", as_of=date(2029, 10, 30))
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert (
        _azure_sku_lifecycle_status("Standard_DC8ds_v3", as_of=date(2029, 10, 31))
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
            vCores=v_cores,
            supportedMemoryPerVcoreMb=4096,
            supportedHaMode=[],
        )

    capability = SimpleNamespace(
        supportedServerVersions=[SimpleNamespace(name="16", status="Available")],
        storageAutoGrowthSupported=None,
        supportedFeatures=[
            SimpleNamespace(name="IndexTuning", status="Enabled"),
            SimpleNamespace(name="AdaptiveAutoVacuumAutoApply", status="Enabled"),
        ],
        supportedServerEditions=[
            SimpleNamespace(
                name="GeneralPurpose",
                supportedStorageEditions=[],
                supportedServerSkus=[_sku("Standard_D2s_v3")],
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
        patch("sc_crawler.vendors._azure._pg_retail_prices", return_value=[]),
    ):
        rows = azure_databases(vendor)
    assert rows[0]["autotuning_advice"] is True
    assert rows[0]["autotuning_apply"] is True

    capability.supportedFeatures = [
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
        patch("sc_crawler.vendors._azure._pg_retail_prices", return_value=[]),
    ):
        rows = azure_databases(vendor)
    assert rows[0]["autotuning_advice"] is True
    assert rows[0]["autotuning_apply"] is False


def test_azure_inventory_databases_fails_loudly_on_unparsable_capabilities():
    """Old snake_case keys (SDK < 3 `as_dict()`) must not silently sync 0 rows."""
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="centralus", api_reference="centralus")]
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    capability = SimpleNamespace(
        supported_server_editions=[
            SimpleNamespace(
                name="GeneralPurpose",
                supported_storage_editions=[],
                supported_server_skus=[
                    SimpleNamespace(name="Standard_D2s_v3", v_cores=2)
                ],
            )
        ],
    )
    with (
        patch.dict("os.environ", {}, clear=False) as env,
        patch(
            "sc_crawler.vendors._azure._pg_database_regions",
            return_value=vendor.regions,
        ),
        patch(
            "sc_crawler.vendors._azure._pg_capabilities",
            return_value=[capability],
        ),
        patch("sc_crawler.vendors._azure._pg_retail_prices", return_value=[]),
    ):
        env.pop("SENTRY_DSN", None)
        with pytest.raises(ValueError, match="parsed no server editions"):
            azure_databases(vendor)


def test_azure_inventory_databases_ha_from_supported_ha_mode():
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="centralus", api_reference="centralus")]
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    capability = SimpleNamespace(
        supportedServerVersions=[
            SimpleNamespace(name="16", status="Available"),
        ],
        storageAutoGrowthSupported="Enabled",
        supportedFeatures=[],
        supportedServerEditions=[
            SimpleNamespace(
                name="Burstable",
                supportedStorageEditions=[],
                supportedServerSkus=[
                    SimpleNamespace(
                        name="Standard_B1ms",
                        vCores=1,
                        supportedMemoryPerVcoreMb=2048,
                        supportedHaMode=["SameZone", "ZoneRedundant"],
                    )
                ],
            ),
            SimpleNamespace(
                name="GeneralPurpose",
                supportedStorageEditions=[],
                supportedServerSkus=[
                    SimpleNamespace(
                        name="Standard_D2s_v3",
                        vCores=2,
                        supportedMemoryPerVcoreMb=4096,
                        supportedHaMode=["SameZone", "ZoneRedundant"],
                    ),
                    SimpleNamespace(
                        name="Standard_D4s_v3",
                        vCores=4,
                        supportedMemoryPerVcoreMb=4096,
                        supportedHaMode=["SameZone"],
                    ),
                ],
            ),
            SimpleNamespace(
                name="MemoryOptimized",
                supportedStorageEditions=[],
                supportedServerSkus=[
                    SimpleNamespace(
                        name="Standard_E2s_v3",
                        vCores=2,
                        supportedMemoryPerVcoreMb=8192,
                        supportedHaMode=["ZoneRedundant"],
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
        patch("sc_crawler.vendors._azure._pg_retail_prices", return_value=[]),
    ):
        rows = azure_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert by_id["Standard_B1ms"]["ha"] == [DatabaseHaLevel.NONE]
    assert by_id["Standard_B1ms"]["family"] == "Burstable"
    assert by_id["Standard_B1ms"]["series"] == "Bs"
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
    assert by_id["Standard_D2s_v3"]["family"] == "General Purpose"
    assert by_id["Standard_D2s_v3"]["series"] == "Dsv3"
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


def test_azure_inventory_databases_adds_quota_hidden_concrete_retail_skus():
    """Concrete Retail Standard_* fills sizes capabilities omitted; series meters do not invent VMs."""
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="westus3", api_reference="westus3")]
    vendor.servers = [
        SimpleNamespace(
            api_reference="Standard_E104ids_v5",
            server_id="Standard_E104ids_v5",
            vcpus=104,
            memory_amount=917504,
        ),
    ]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    capability = SimpleNamespace(
        supportedServerVersions=[SimpleNamespace(name="16", status="Available")],
        storageAutoGrowthSupported="Enabled",
        supportedFeatures=[
            SimpleNamespace(name="IndexTuning", status="Enabled"),
        ],
        supportedServerEditions=[
            SimpleNamespace(
                name="GeneralPurpose",
                supportedStorageEditions=[],
                supportedServerSkus=[
                    SimpleNamespace(
                        name="Standard_D2s_v3",
                        vCores=2,
                        supportedMemoryPerVcoreMb=4096,
                        supportedHaMode=["SameZone", "ZoneRedundant"],
                    )
                ],
            ),
            # Same series as the quota-hidden Retail size; Retail must not invent new series.
            SimpleNamespace(
                name="MemoryOptimized",
                supportedStorageEditions=[],
                supportedServerSkus=[
                    SimpleNamespace(
                        name="Standard_E2ds_v5",
                        vCores=2,
                        supportedMemoryPerVcoreMb=8192,
                        supportedHaMode=["SameZone", "ZoneRedundant"],
                    )
                ],
            ),
        ],
    )
    retail = [
        {
            # Series meter alone must not invent Standard_D*s_v6 from the VM catalog.
            "armSkuName": (
                "Azure_Database_for_PostgreSQL_Flexible_Server_"
                "General_Purpose_Dsv6_Series_Compute_1_vCore"
            ),
            "productName": (
                "Azure Database for PostgreSQL Flexible Server "
                "General Purpose Dsv6 Series Compute"
            ),
            "meterName": "1 vCore",
            "skuName": "1 vCore",
        },
        {
            "armSkuName": "Standard_E104ids_v5",
            "productName": (
                "Azure Database for PostgreSQL Flexible Server "
                "Memory Optimized Edsv5 Series Compute"
            ),
            "meterName": "vCore",
            "skuName": "104 vCore",
        },
        {
            "armSkuName": "1 vCore",
            "productName": "Azure Cosmos DB for PostgreSQL Compute- Burstable",
            "meterName": "vCore",
            "skuName": "1 vCore",
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
        patch("sc_crawler.vendors._azure._pg_retail_prices", return_value=retail),
    ):
        rows = azure_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert set(by_id) == {
        "Standard_D2s_v3",
        "Standard_E2ds_v5",
        "Standard_E104ids_v5",
    }
    assert by_id["Standard_D2s_v3"]["family"] == "General Purpose"
    assert by_id["Standard_D2s_v3"]["series"] == "Dsv3"
    assert by_id["Standard_D2s_v3"]["autotuning_advice"] is True
    assert by_id["Standard_D2s_v3"]["storage_extra_autosize"] is True
    assert by_id["Standard_D2s_v3"]["ha"] == [
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.SINGLE_ZONE,
        DatabaseHaLevel.NONE,
    ]
    e104 = by_id["Standard_E104ids_v5"]
    assert e104["family"] == "Memory Optimized"
    assert e104["series"] == "Edsv5"
    assert e104["vcpus"] == 104
    assert e104["memory_amount"] == 917504
    assert e104["engine_versions"] == ["16"]
    assert e104["api_reference_object"] == {"sku_name": "MO_Standard_E104ids_v5"}


def test_azure_inventory_databases_skips_series_meter_vm_sizes():
    """Series meters must not invent VM-only sizes Flexible Server never lists."""
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="westeurope", api_reference="westeurope")]
    vendor.servers = [
        SimpleNamespace(
            api_reference=name, server_id=name, vcpus=8, memory_amount=32768
        )
        for name in (
            "Standard_DC8as_v5",
            "Standard_DC8ads_v5",
            "Standard_DC8es_v6",
            "Standard_EC8as_v5",
            "Standard_D2s_v6",
            "Standard_D2ds_v6",
        )
    ]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    capability = SimpleNamespace(
        supportedServerVersions=[SimpleNamespace(name="16", status="Available")],
        storageAutoGrowthSupported="Enabled",
        supportedFeatures=[],
        supportedServerEditions=[
            SimpleNamespace(
                name="GeneralPurpose",
                supportedStorageEditions=[],
                supportedServerSkus=[
                    SimpleNamespace(
                        name="Standard_DC8ads_v5",
                        vCores=8,
                        supportedMemoryPerVcoreMb=4096,
                        supportedHaMode=[],
                    )
                ],
            )
        ],
    )
    retail = [
        {
            "armSkuName": (
                "Azure_Database_for_PostgreSQL_Flexible_Server_"
                f"{label}_Series_Compute_1_vCore"
            ),
            "productName": (
                "Azure Database for PostgreSQL Flexible Server "
                f"{product} Series Compute"
            ),
            "meterName": "1 vCore",
            "skuName": "1 vCore",
        }
        for label, product in (
            ("Confidential_Compute_DCasv5", "Confidential Compute DCasv5"),
            ("Confidential_Compute_DCesv6", "Confidential Compute DCesv6"),
            ("Confidential_Compute_ECasv5", "Confidential Compute ECasv5"),
            ("General_Purpose_Dsv6", "General Purpose Dsv6"),
        )
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
        patch("sc_crawler.vendors._azure._pg_retail_prices", return_value=retail),
    ):
        rows = azure_databases(vendor)
    assert {row["database_id"] for row in rows} == {"Standard_DC8ads_v5"}


def test_azure_inventory_databases_keeps_confidential_only_in_acc_regions():
    """ConfidentialVM SKUs outside ACC regions (e.g. Korea DCadsv6) are dropped."""
    vendor = Mock(vendor_id="azure")
    vendor.regions = [
        Mock(region_id="westeurope", api_reference="westeurope"),
        Mock(region_id="koreacentral", api_reference="koreacentral"),
    ]
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )

    def caps_for(location):
        if location == "westeurope":
            skus = [
                SimpleNamespace(
                    name="Standard_DC8ads_v5",
                    vCores=8,
                    supportedMemoryPerVcoreMb=4096,
                    supportedHaMode=[],
                    securityProfile="ConfidentialVM",
                    status=None,
                ),
                SimpleNamespace(
                    name="Standard_D2ds_v6",
                    vCores=2,
                    supportedMemoryPerVcoreMb=4096,
                    supportedHaMode=[],
                    securityProfile=None,
                    status=None,
                ),
            ]
        else:
            skus = [
                SimpleNamespace(
                    name="Standard_DC8ads_v6",
                    vCores=8,
                    supportedMemoryPerVcoreMb=4096,
                    supportedHaMode=[],
                    securityProfile="ConfidentialVM",
                    status=None,
                ),
            ]
        return [
            SimpleNamespace(
                supportedServerVersions=[
                    SimpleNamespace(name="16", status="Available")
                ],
                storageAutoGrowthSupported="Enabled",
                supportedFeatures=[],
                supportedServerEditions=[
                    SimpleNamespace(
                        name="GeneralPurpose",
                        supportedStorageEditions=[],
                        supportedServerSkus=skus,
                    )
                ],
            )
        ]

    with (
        patch(
            "sc_crawler.vendors._azure._pg_database_regions",
            return_value=vendor.regions,
        ),
        patch(
            "sc_crawler.vendors._azure._pg_capabilities",
            side_effect=caps_for,
        ),
        patch("sc_crawler.vendors._azure._pg_retail_prices", return_value=[]),
    ):
        rows = azure_databases(vendor)
    assert {row["database_id"] for row in rows} == {
        "Standard_DC8ads_v5",
        "Standard_D2ds_v6",
    }


def test_azure_inventory_databases_retail_requires_capabilities_series():
    """Retail Standard_* cannot introduce a series never listed in capabilities."""
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="westus3", api_reference="westus3")]
    vendor.servers = [
        SimpleNamespace(
            api_reference="Standard_M32dms_v2",
            server_id="Standard_M32dms_v2",
            vcpus=32,
            memory_amount=896000,
        ),
        SimpleNamespace(
            api_reference="Standard_E104ids_v5",
            server_id="Standard_E104ids_v5",
            vcpus=104,
            memory_amount=917504,
        ),
    ]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    capability = SimpleNamespace(
        supportedServerVersions=[SimpleNamespace(name="16", status="Available")],
        storageAutoGrowthSupported="Enabled",
        supportedFeatures=[],
        supportedServerEditions=[
            SimpleNamespace(
                name="MemoryOptimized",
                supportedStorageEditions=[],
                supportedServerSkus=[
                    SimpleNamespace(
                        name="Standard_E2ds_v5",
                        vCores=2,
                        supportedMemoryPerVcoreMb=8192,
                        supportedHaMode=[],
                        securityProfile=None,
                        status=None,
                    )
                ],
            )
        ],
    )
    retail = [
        {
            "armSkuName": "Standard_M32dms_v2",
            "productName": (
                "Azure Database for PostgreSQL Flexible Server Mdsv2 Series Compute"
            ),
            "meterName": "vCore",
            "skuName": "32 vCore",
        },
        {
            "armSkuName": "Standard_E104ids_v5",
            "productName": (
                "Azure Database for PostgreSQL Flexible Server "
                "Memory Optimized Edsv5 Series Compute"
            ),
            "meterName": "vCore",
            "skuName": "104 vCore",
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
        patch("sc_crawler.vendors._azure._pg_retail_prices", return_value=retail),
    ):
        rows = azure_databases(vendor)
    assert {row["database_id"] for row in rows} == {
        "Standard_E2ds_v5",
        "Standard_E104ids_v5",
    }


def test_azure_burstable_storage_extra_max_excludes_premium_ssd_v2():
    from sc_crawler.utils import _GIB_TO_GB

    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="centralus", api_reference="centralus")]
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    premium_ssd_max_mib = 32_767 * 1024
    premium_ssd_v2_max_mib = 65_536 * 1024
    capability = SimpleNamespace(
        supportedServerVersions=[SimpleNamespace(name="16", status="Available")],
        storageAutoGrowthSupported="Enabled",
        supportedFeatures=[],
        supportedServerEditions=[
            SimpleNamespace(
                name="Burstable",
                supportedStorageEditions=[
                    SimpleNamespace(
                        name="ManagedDisk",
                        reason=None,
                        supportedStorageMb=[
                            SimpleNamespace(
                                storageSizeMb=32 * 1024,
                                maximumStorageSizeMb=premium_ssd_max_mib,
                            )
                        ],
                    ),
                    SimpleNamespace(
                        name="ManagedDiskV2",
                        reason=None,
                        supportedStorageMb=[
                            SimpleNamespace(
                                storageSizeMb=32 * 1024,
                                maximumStorageSizeMb=premium_ssd_v2_max_mib,
                            )
                        ],
                    ),
                ],
                supportedServerSkus=[
                    SimpleNamespace(
                        name="Standard_B2s",
                        vCores=2,
                        supportedMemoryPerVcoreMb=2048,
                        supportedHaMode=[],
                    )
                ],
            ),
            SimpleNamespace(
                name="GeneralPurpose",
                supportedStorageEditions=[
                    SimpleNamespace(
                        name="ManagedDisk",
                        reason=None,
                        supportedStorageMb=[
                            SimpleNamespace(
                                storageSizeMb=32 * 1024,
                                maximumStorageSizeMb=premium_ssd_max_mib,
                            )
                        ],
                    ),
                    SimpleNamespace(
                        name="ManagedDiskV2",
                        reason=None,
                        supportedStorageMb=[
                            SimpleNamespace(
                                storageSizeMb=32 * 1024,
                                maximumStorageSizeMb=premium_ssd_v2_max_mib,
                            )
                        ],
                    ),
                ],
                supportedServerSkus=[
                    SimpleNamespace(
                        name="Standard_D2s_v3",
                        vCores=2,
                        supportedMemoryPerVcoreMb=4096,
                        supportedHaMode=["SameZone"],
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
        patch("sc_crawler.vendors._azure._pg_retail_prices", return_value=[]),
    ):
        rows = azure_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert by_id["Standard_B2s"]["storage_extra_max"] == round(32_767 * _GIB_TO_GB)
    assert by_id["Standard_D2s_v3"]["storage_extra_max"] == round(65_536 * _GIB_TO_GB)
    # Premium SSD v2 is not for Burstable, even if the API lists it
    assert by_id["Standard_B2s"]["compatible_storage_ids"] == ["ManagedDisk"]
    assert by_id["Standard_D2s_v3"]["compatible_storage_ids"] == [
        "ManagedDisk",
        "ManagedDiskV2",
    ]


def test_azure_inventory_database_prices_emit_ha_rows():
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="centralus", api_reference="centralus")]
    vendor.databases = [
        Mock(
            database_id="Standard_B1ms",
            family="Burstable",
            vcpus=1,
            ha=[DatabaseHaLevel.NONE],
            status=Status.ACTIVE,
        ),
        Mock(
            database_id="Standard_D2s_v3",
            family="General Purpose",
            vcpus=2,
            ha=[
                DatabaseHaLevel.MULTI_ZONE,
                DatabaseHaLevel.SINGLE_ZONE,
                DatabaseHaLevel.NONE,
            ],
            status=Status.ACTIVE,
        ),
        Mock(
            database_id="Standard_B2ms",
            family="Burstable",
            vcpus=2,
            ha=[DatabaseHaLevel.NONE],
            status=Status.PLANNED_FOR_RETIREMENT,
        ),
        Mock(
            database_id="Standard_D16ps_v",
            family="General Purpose",
            vcpus=16,
            ha=[DatabaseHaLevel.NONE],
            status=Status.INACTIVE,
        ),
    ]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
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
        {
            "armSkuName": "Standard_B2ms",
            "productName": (
                "Azure Database for PostgreSQL Flexible Server "
                "Burstable BS Series Compute"
            ),
            "meterName": "B2ms vCore",
            "skuName": "B2ms",
            "retailPrice": 0.136,
            "currencyCode": "USD",
        },
    ]
    with (
        patch(
            "sc_crawler.vendors._azure._pg_database_regions",
            return_value=vendor.regions,
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
    assert (
        by_key[
            (
                "Standard_B2ms",
                DatabaseHaLevel.NONE,
                DatabaseHaStrategy.NONE,
            )
        ]
        == 0.136
    )
    assert not any(row["database_id"] == "Standard_D16ps_v" for row in prices)


def test_azure_inventory_database_prices_without_regional_capabilities():
    """Retail meters are enough; OfferRestricted empty capabilities must not block prices."""
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="eastus", api_reference="eastus")]
    vendor.databases = [
        Mock(
            database_id="Standard_D16ds_v5",
            family="General Purpose",
            vcpus=16,
            ha=[DatabaseHaLevel.NONE],
            status=Status.ACTIVE,
        ),
        Mock(
            database_id="Standard_D16ds_v6",
            family="General Purpose",
            vcpus=16,
            ha=[
                DatabaseHaLevel.MULTI_ZONE,
                DatabaseHaLevel.SINGLE_ZONE,
                DatabaseHaLevel.NONE,
            ],
            status=Status.ACTIVE,
        ),
    ]
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    retail = [
        {
            "armSkuName": "Standard_D16ds_v5",
            "productName": (
                "Azure Database for PostgreSQL Flexible Server "
                "General Purpose Ddsv5 Series Compute"
            ),
            "meterName": "vCore",
            "skuName": "16 vCore",
            "retailPrice": 1.424,
            "currencyCode": "USD",
        },
        {
            "armSkuName": (
                "AzureDB_PostgreSQL_Flexible_Server_"
                "General_Purpose_Ddsv6_Series_Compute"
            ),
            "productName": (
                "Azure Database for PostgreSQL Flexible Server "
                "General Purpose Ddsv6 Series Compute"
            ),
            "meterName": "vCore",
            "skuName": "vCore",
            "retailPrice": 0.112,
            "currencyCode": "USD",
        },
    ]
    with (
        patch(
            "sc_crawler.vendors._azure._pg_database_regions",
            return_value=vendor.regions,
        ),
        patch(
            "sc_crawler.vendors._azure._pg_retail_prices",
            return_value=retail,
        ),
        patch(
            "sc_crawler.vendors._azure._pg_capabilities",
            side_effect=AssertionError("prices must not use capabilities"),
        ),
    ):
        prices = azure_database_prices(vendor)
    by_key = {
        (row["database_id"], row["ha"], row["ha_strategy"]): row["price"]
        for row in prices
    }
    assert (
        by_key[("Standard_D16ds_v5", DatabaseHaLevel.NONE, DatabaseHaStrategy.NONE)]
        == 1.424
    )
    assert (
        by_key[("Standard_D16ds_v6", DatabaseHaLevel.NONE, DatabaseHaStrategy.NONE)]
        == 1.792
    )
    assert (
        by_key[
            (
                "Standard_D16ds_v6",
                DatabaseHaLevel.MULTI_ZONE,
                DatabaseHaStrategy.PASSIVE_STANDBY,
            )
        ]
        == 3.584
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

    # The "1 vCore" meter wins over a sized meter, matching the public pricing page;
    # sized meters can be stale or copy-pasted (westcentralus D8ds_v5 == D16ds_v5).
    full_sku = {
        "armSkuName": "Standard_D16ds_v5",
        "productName": (
            "Azure Database for PostgreSQL Flexible Server "
            "General Purpose Ddsv5 Series Compute"
        ),
        "meterName": "vCore",
        "skuName": "16 vCore",
        "retailPrice": 2.8,
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
    assert item is ddsv5_per_vcore
    assert _pg_hourly_compute_price(item, 16, database_id="Standard_D16ds_v5") == 1.424


@pytest.mark.parametrize(
    "product,series",
    [
        ("Azure Database for PostgreSQL Flexible Server Mdsv2 Series Compute", "Mdsv2"),
        (
            "Azure Database for PostgreSQL Flexible Server General Purpose AMD Dadsv5 Series Compute",
            "Dadsv5",
        ),
        (
            "Azure Database for PostgreSQL Flexible Server Memory Optimized Edsv5 Series Compute",
            "Edsv5",
        ),
    ],
)
def test_pg_product_series_re(product, series):
    assert _PG_PRODUCT_SERIES_RE.search(product)["series"] == series


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
        supportedServerEditions=[
            SimpleNamespace(
                supportedStorageEditions=[
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


@pytest.mark.parametrize(
    "size,sku_family,series",
    [
        # the SKU family spells these differently from the database series
        ("Standard_D2s_v3", "DSv3", "Dsv3"),
        ("Standard_D2ds_v5", "DDSv5", "Ddsv5"),
        ("Standard_B1ms", "BS", "Bs"),
        ("Standard_D4ads_v6", "Dadv6", "Dadsv6"),
        ("Standard_E4ads_v6", "Eadv6", "Eadsv6"),
        # sizes unknown to the database parser keep the SKU family
        ("Standard_NC24ads_A100_v4", "NCADSA100v4", "NCADSA100v4"),
    ],
)
def test_azure_vm_series_matches_database_series(size, sku_family, series):
    assert _vm_series(size, sku_family) == series


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
        supportedServerVersions=[
            SimpleNamespace(name="15", status="Available"),
            SimpleNamespace(name="16", status="Available"),
            SimpleNamespace(name="14", status="Disabled"),
            SimpleNamespace(name=None, status="Available"),
        ]
    )
    assert _pg_engine_versions(capability) == ["15", "16"]


def _disk(name, size, tier, **capabilities):
    return {
        "resourceType": "disks",
        "name": name,
        "size": size,
        "tier": tier,
        "capabilities": [{"name": k, "value": v} for k, v in capabilities.items()],
    }


_DISK_RESOURCES = [
    _disk("Premium_LRS", "P10", "Premium", MaxSizeGiB="128", MaxIOps="500"),
    _disk("Premium_LRS", "P1", "Premium", MaxSizeGiB="4", MaxIOps="120"),
    _disk("Premium_ZRS", "P10", "Premium", MaxSizeGiB="128"),
    _disk("StandardSSD_LRS", "E10", "Standard", MaxSizeGiB="128"),
    _disk("Standard_LRS", "S4", "Standard", MaxSizeGiB="32"),
    # provisioned capacity disks have no size tiers
    _disk("PremiumV2_LRS", "P", "Premium", MaxSizeGiB="65536"),
    _disk("UltraSSD_LRS", "U", "Ultra", MaxSizeGiB="65536"),
    # a tier without size is ignored, and other resource types too
    _disk("Premium_LRS", "P99", "Premium"),
    {"resourceType": "virtualMachines", "name": "Standard_D2s_v5", "size": "D2s_v5"},
]


def test_azure_storage_meter_mapping_is_derived_from_the_disk_skus():
    _storage_meter_mapping.cache_clear()
    with patch(
        "sc_crawler.vendors._azure._compute_resources", return_value=_DISK_RESOURCES
    ):
        mapping = _storage_meter_mapping()
    _storage_meter_mapping.cache_clear()
    assert mapping == {
        "P10 LRS Disk": ("Premium_LRS", 128),
        "P1 LRS Disk": ("Premium_LRS", 4),
        "P10 ZRS Disk": ("Premium_ZRS", 128),
        "E10 LRS Disk": ("StandardSSD_LRS", 128),
        "S4 LRS Disk": ("Standard_LRS", 32),
        "Premium LRS Provisioned Capacity": ("PremiumV2_LRS", 1),
        "Ultra LRS Provisioned Capacity": ("UltraSSD_LRS", 1),
    }


def test_azure_storage_prices_use_the_derived_meter_mapping():
    _storage_meter_mapping.cache_clear()
    vendor = Mock(vendor_id="azure")
    vendor.regions = [Mock(region_id="westeurope")]
    vendor.storages = [Mock(storage_id="Premium_LRS"), Mock(storage_id="UltraSSD_LRS")]
    retail = [
        {
            "meterName": "P10 LRS Disk",
            "armRegionName": "westeurope",
            "unitOfMeasure": "1/Month",
            "retailPrice": 19.7,
            "currencyCode": "USD",
        },
        {
            "meterName": "Ultra LRS Provisioned Capacity",
            "armRegionName": "westeurope",
            "unitOfMeasure": "1 GiB/Hour",
            "retailPrice": 0.000164,
            "currencyCode": "USD",
        },
        # not a disk meter: ignored
        {
            "meterName": "P10 LRS Disk Mount",
            "armRegionName": "westeurope",
            "unitOfMeasure": "1/Month",
            "retailPrice": 1,
            "currencyCode": "USD",
        },
    ]
    with (
        patch(
            "sc_crawler.vendors._azure._compute_resources",
            return_value=_DISK_RESOURCES,
        ),
        patch(
            "sc_crawler.vendors._azure._get_storage_retail_prices", return_value=retail
        ),
    ):
        items = inventory_storage_prices(vendor)
    _storage_meter_mapping.cache_clear()
    assert {item["storage_id"] for item in items} == {"Premium_LRS", "UltraSSD_LRS"}
    premium = next(item for item in items if item["storage_id"] == "Premium_LRS")
    # 19.7 USD for a 128 GiB disk, per GB and month
    assert premium["price"] == round(19.7 / 128 / (1024**3 / 1000**3), 4)


def test_azure_storages_use_the_derived_disk_sizes():
    _storage_meter_mapping.cache_clear()
    caps = {"MinSizeGiB": "0", "MaxIOps": "500", "MaxBandwidthMBps": "100"}
    resources = [
        _disk("Premium_LRS", "P10", "Premium", MaxSizeGiB="128", **caps),
        _disk("Premium_LRS", "P1", "Premium", MaxSizeGiB="4", **caps),
    ]
    with patch("sc_crawler.vendors._azure._compute_resources", return_value=resources):
        items = inventory_storages(Mock(vendor_id="azure"))
    _storage_meter_mapping.cache_clear()
    assert len(items) == 1
    # min and max of the tiers (P1 = 4 GiB ... P10 = 128 GiB), in GB
    assert items[0]["min_size"] == round(4 * 1024**3 / 1000**3)
    assert items[0]["max_size"] == round(128 * 1024**3 / 1000**3)


@pytest.mark.parametrize(
    "edition,family",
    [
        # edition names of the PostgreSQL flexible server capabilities API
        ("Burstable", "Burstable"),
        ("GeneralPurpose", "General Purpose"),
        ("MemoryOptimized", "Memory Optimized"),
        (None, None),
        ("", None),
    ],
)
def test_azure_pg_edition_family_from_the_api_edition_name(edition, family):
    assert _pg_edition_family(edition) == family


def _vm(name, **capabilities):
    return {
        "resourceType": "virtualMachines",
        "name": name,
        "capabilities": [{"name": k, "value": v} for k, v in capabilities.items()],
    }


def test_azure_vm_retirement_dates_from_the_compute_resources():
    resources = [
        _vm("Standard_A2m_v2", RetirementDateUtc="11/15/2028"),
        # placeholder for no retirement date
        _vm("Standard_D2s_v5", RetirementDateUtc="01/01/9999"),
        _vm("Standard_D4s_v5", vCPUs="4"),
        _vm("Standard_Bad", RetirementDateUtc="soon"),
        {
            "resourceType": "disks",
            "name": "Premium_LRS",
            "capabilities": [{"name": "RetirementDateUtc", "value": "01/01/2027"}],
        },
    ]
    # the imported function is the real one, only the module attribute is patched
    _vm_retirement_dates.cache_clear()
    with patch("sc_crawler.vendors._azure._compute_resources", return_value=resources):
        dates = _vm_retirement_dates()
    _vm_retirement_dates.cache_clear()
    assert dates == {"Standard_A2m_v2": date(2028, 11, 15)}


def test_azure_sku_lifecycle_status_prefers_the_api_retirement_date():
    dates = {"Standard_GS5": date(2028, 5, 1)}
    with patch("sc_crawler.vendors._azure._vm_retirement_dates", return_value=dates):
        # before the API date: planned, on or after it: retired. The rules of the docs
        # would say 2028-11-15 for the G-series.
        assert (
            _azure_sku_lifecycle_status("Standard_GS5", as_of=date(2028, 4, 30))
            == Status.PLANNED_FOR_RETIREMENT
        )
        assert (
            _azure_sku_lifecycle_status("Standard_GS5", as_of=date(2028, 6, 1))
            == Status.RETIRED
        )
        # a size without API date falls back to the rules
        assert (
            _azure_sku_lifecycle_status("Standard_D2", as_of=date(2028, 4, 30))
            == Status.PLANNED_FOR_RETIREMENT
        )
        assert (
            _azure_sku_lifecycle_status("Standard_D2s_v5", as_of=date(2030, 1, 1))
            == Status.ACTIVE
        )


def test_azure_database_compatible_storage_ids_are_the_union_over_the_regions():
    vendor = Mock(vendor_id="azure")
    vendor.regions = [
        Mock(region_id="westeurope", api_reference="westeurope"),
        Mock(region_id="centralus", api_reference="centralus"),
    ]
    vendor.servers = []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    unsupported = "Specified Storage Edition not supported in this region."

    def _storage(name, reason=None):
        return SimpleNamespace(name=name, reason=reason, supportedStorageMb=[])

    def _capability(storages):
        return SimpleNamespace(
            supportedServerVersions=[SimpleNamespace(name="16", status="Available")],
            storageAutoGrowthSupported=None,
            supportedFeatures=[],
            supportedServerEditions=[
                SimpleNamespace(
                    name="GeneralPurpose",
                    supportedStorageEditions=storages,
                    supportedServerSkus=[
                        SimpleNamespace(
                            name="Standard_D2s_v3",
                            vCores=2,
                            supportedMemoryPerVcoreMb=4096,
                            supportedHaMode=[],
                        )
                    ],
                )
            ],
        )

    capabilities = {
        # Premium SSD v2 and Ultra are not supported in one region each
        "westeurope": _capability(
            [
                _storage("ManagedDisk"),
                _storage("ManagedDiskV2", unsupported),
                _storage("UltraDisk"),
            ]
        ),
        "centralus": _capability(
            [
                _storage("ManagedDisk"),
                _storage("ManagedDiskV2"),
                _storage("UltraDisk", unsupported),
            ]
        ),
    }
    with (
        patch(
            "sc_crawler.vendors._azure._pg_database_regions",
            return_value=vendor.regions,
        ),
        patch(
            "sc_crawler.vendors._azure._pg_capabilities",
            side_effect=lambda location: [capabilities[location]],
        ),
        patch("sc_crawler.vendors._azure._pg_retail_prices", return_value=[]),
    ):
        rows = azure_databases(vendor)
    # a type available in at least one region counts, whatever the last region says
    assert rows[0]["compatible_storage_ids"] == [
        "ManagedDisk",
        "ManagedDiskV2",
        "UltraDisk",
    ]


def _vm_size(name, premium_io, ultra_top=None, ultra_zone=False):
    capabilities = [{"name": "PremiumIO", "value": premium_io}]
    if ultra_top is not None:
        capabilities.append({"name": "UltraSSDAvailable", "value": ultra_top})
    zone_capabilities = (
        [{"name": "UltraSSDAvailable", "value": "True"}] if ultra_zone else []
    )
    return {
        "resourceType": "virtualMachines",
        "name": name,
        "capabilities": capabilities,
        "locationInfo": [{"zoneDetails": [{"capabilities": zone_capabilities}]}],
    }


def test_azure_disk_names_and_ultra_vm_sizes_from_the_compute_resources():
    resources = [
        {"resourceType": "disks", "name": "Premium_LRS"},
        {"resourceType": "disks", "name": "Standard_LRS"},
        {"resourceType": "disks", "name": "Premium_LRS"},
        # Ultra on the size, in a zone of another region, or nowhere
        _vm_size("Standard_D2s_v5", "True", ultra_top="True"),
        _vm_size("Standard_E2s_v5", "True", ultra_top="False", ultra_zone=True),
        _vm_size("Standard_E2s_v5", "True", ultra_top="False"),
        _vm_size("Standard_B2s", "True", ultra_top="False"),
    ]
    _disk_sku_names.cache_clear()
    _ultra_disk_vm_sizes.cache_clear()
    with patch("sc_crawler.vendors._azure._compute_resources", return_value=resources):
        assert _disk_sku_names() == ["Premium_LRS", "Standard_LRS"]
        assert _ultra_disk_vm_sizes() == {"Standard_D2s_v5", "Standard_E2s_v5"}
    _disk_sku_names.cache_clear()
    _ultra_disk_vm_sizes.cache_clear()


def test_azure_compatible_storage_ids_by_vm_size_capabilities():
    all_disks = [
        "PremiumV2_LRS",
        "Premium_LRS",
        "Premium_ZRS",
        "StandardSSD_LRS",
        "StandardSSD_ZRS",
        "Standard_LRS",
        "UltraSSD_LRS",
    ]
    with (
        patch("sc_crawler.vendors._azure._disk_sku_names", return_value=all_disks),
        patch(
            "sc_crawler.vendors._azure._ultra_disk_vm_sizes",
            return_value=frozenset({"Standard_D2s_v5", "Standard_D2_v5"}),
        ),
    ):
        # premium storage capable and Ultra capable: every disk type
        assert _compatible_storage_ids(_vm_size("Standard_D2s_v5", "True")) == all_disks
        # premium storage capable, not Ultra: no Ultra disk
        assert _compatible_storage_ids(_vm_size("Standard_E2s_v5", "True")) == [
            d for d in all_disks if d != "UltraSSD_LRS"
        ]
        # no premium storage: only Standard disks (no Premium SSD, Premium SSD v2 or
        # Ultra, even if the API says so)
        assert _compatible_storage_ids(_vm_size("Standard_D2_v5", "False")) == [
            "StandardSSD_LRS",
            "StandardSSD_ZRS",
            "Standard_LRS",
        ]


def test_azure_unknown_disk_type_is_not_added_and_warned_once():
    _warn_unknown_disk.cache_clear()
    with (
        patch(
            "sc_crawler.vendors._azure._disk_sku_names",
            return_value=["Standard_LRS", "FutureDisk_LRS"],
        ),
        patch("sc_crawler.vendors._azure.logger") as logger,
    ):
        assert _compatible_storage_ids(_vm_size("Standard_D2s_v5", "True")) == [
            "Standard_LRS"
        ]
        assert _compatible_storage_ids(_vm_size("Standard_D4s_v5", "True")) == [
            "Standard_LRS"
        ]
    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert len(warnings) == 1
    assert "FutureDisk_LRS" in warnings[0]
