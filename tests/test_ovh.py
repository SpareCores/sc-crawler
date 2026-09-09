"""Unit tests for OVHcloud vendor module."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from sc_crawler.table_fields import (
    Allocation,
    DatabaseEngine,
    DatabaseHaLevel,
    DatabaseHaStrategy,
    DatabaseSecurityFeature,
    DatabaseStorageScope,
    DatabaseWireProtocol,
    PriceUnit,
    Status,
)
from sc_crawler.vendors._ovh import (
    _client,
    _get_catalog,
    _get_database_availability,
    _get_database_capabilities,
    _get_gpu_info,
    _get_project_id,
    _get_region,
    _get_regions,
    _get_server_family,
    inventory_compliance_frameworks,
    inventory_database_prices,
    inventory_database_storage_prices,
    inventory_database_storages,
    inventory_databases,
    inventory_regions,
)

_MIB_PER_GIB = 1024


@pytest.fixture(autouse=True)
def mock_ovh_client():
    """Mock OVH client and most common API endpoints for all tests."""
    _client.cache_clear()
    _get_project_id.cache_clear()
    _get_regions.cache_clear()
    _get_region.cache_clear()
    _get_catalog.cache_clear()
    _get_database_availability.cache_clear()
    _get_database_capabilities.cache_clear()

    with (
        patch("sc_crawler.vendors._ovh._client") as mock_client_factory,
        patch("sc_crawler.vendors._ovh.getenv") as mock_getenv,
    ):
        mock = Mock()
        mock_client_factory.return_value = mock

        def mock_env_side_effect(key, default=None):
            if key == "OVH_PROJECT_ID":
                return None
            if key == "OVH_SUBSIDIARY":
                return default if default else "IE"
            return default

        mock_getenv.side_effect = mock_env_side_effect

        def default_fake_get(path, *args, **kwargs):
            if path == "/cloud/project":
                return ["test-project"]
            # mock 2 regions: 3AZ in EU + 1AZ in AP
            if path == "/cloud/project/test-project/region":
                return ["EU-WEST-PAR", "AP-SOUTH-MUM"]
            if path == "/cloud/project/test-project/region/EU-WEST-PAR":
                return {
                    "datacenterLocation": "PAR",
                    "availabilityZones": [
                        "eu-west-par-a",
                        "eu-west-par-b",
                        "eu-west-par-c",
                    ],
                }
            if path == "/cloud/project/test-project/region/AP-SOUTH-MUM":
                return {
                    "datacenterLocation": "YNM",
                    "availabilityZones": ["ap-south-mum-a"],
                }
            raise RuntimeError(f"Unmocked OVH API call: {path}")

        mock.get.side_effect = default_fake_get
        yield mock


def test_mock_ovh_client():
    """Test mock OVH client API endpoints."""
    # direct API call
    from sc_crawler.vendors._ovh import _client

    assert _client().get("/cloud/project") == ["test-project"]
    # helpers
    assert _get_project_id() == "test-project"
    assert len(_get_regions()) == 2
    assert _get_regions()[0] == "EU-WEST-PAR"
    assert len(_get_region("EU-WEST-PAR")["availabilityZones"]) == 3
    assert _get_regions()[1] == "AP-SOUTH-MUM"
    assert len(_get_region("AP-SOUTH-MUM")["availabilityZones"]) == 1


class TestGetServerFamily:
    """Tests for _get_server_family function."""

    def test_general_purpose_family(self):
        """Test General Purpose server family detection."""
        assert _get_server_family("b2-7") == "General Purpose"
        assert _get_server_family("b3-128") == "General Purpose"

    def test_compute_optimized_family(self):
        """Test Compute Optimized server family detection."""
        assert _get_server_family("c2-30") == "Compute Optimized"
        assert _get_server_family("c3-64") == "Compute Optimized"

    def test_memory_optimized_family(self):
        """Test Memory Optimized server family detection."""
        assert _get_server_family("r2-120") == "Memory Optimized"
        assert _get_server_family("r3-256") == "Memory Optimized"

    def test_discovery_family(self):
        """Test Discovery server family detection."""
        assert _get_server_family("d2-8") == "Discovery"

    def test_storage_optimized_family(self):
        """Test Storage Optimized server family detection."""
        assert _get_server_family("i1-90") == "Storage Optimized"

    def test_metal_family(self):
        """Test Metal server family detection."""
        assert _get_server_family("bm-s1") == "Metal"
        assert _get_server_family("bm-m1") == "Metal"

    def test_gpu_family(self):
        """Test GPU server family detection."""
        assert _get_server_family("t1-45") == "Cloud GPU"
        assert _get_server_family("t2-90") == "Cloud GPU"
        assert _get_server_family("a10-180") == "Cloud GPU"
        assert _get_server_family("h100-760") == "Cloud GPU"
        assert _get_server_family("l4-90") == "Cloud GPU"
        assert _get_server_family("rtx5000-28") == "Cloud GPU"

    def test_unknown_family(self):
        """Test unknown server family returns None."""
        assert _get_server_family("unknown-type") is None


class TestGetGpuInfo:
    """Tests for _get_gpu_info function."""

    def test_h100_instances(self):
        """Test H100 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("h100-380")
        assert count == 1
        assert memory == 80 * _MIB_PER_GIB
        assert mfr == "NVIDIA"
        assert family == "Hopper"
        assert model == "H100"

        count, memory, _, _, _ = _get_gpu_info("h100-760")
        assert count == 2
        assert memory == 160 * _MIB_PER_GIB

    def test_a100_instances(self):
        """Test A100 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("a100-180")
        assert count == 1
        assert memory == 80 * _MIB_PER_GIB
        assert mfr == "NVIDIA"
        assert family == "Ampere"
        assert model == "A100"

    def test_a10_instances(self):
        """Test A10 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("a10-45")
        assert count == 1
        assert memory == 24 * _MIB_PER_GIB
        assert mfr == "NVIDIA"
        assert family == "Ampere"
        assert model == "A10"

        count, memory, _, _, _ = _get_gpu_info("a10-180")
        assert count == 4
        assert memory == 96 * _MIB_PER_GIB

    def test_l40s_instances(self):
        """Test L40S GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("l40s-90")
        assert count == 1
        assert memory == 48 * _MIB_PER_GIB
        assert mfr == "NVIDIA"
        assert family == "Ada Lovelace"
        assert model == "L40S"

    def test_l4_instances(self):
        """Test L4 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("l4-90")
        assert count == 1
        assert memory == 24 * _MIB_PER_GIB
        assert mfr == "NVIDIA"
        assert family == "Ada Lovelace"
        assert model == "L4"

    def test_v100s_instances(self):
        """Test V100S GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("t2-45")
        assert count == 1
        assert memory == 32 * _MIB_PER_GIB
        assert mfr == "NVIDIA"
        assert family == "Volta"
        assert model == "V100S"

        # Test LE variant
        count, memory, _, _, _ = _get_gpu_info("t2-le-90")
        assert count == 2
        assert memory == 64 * _MIB_PER_GIB

    def test_v100_instances(self):
        """Test V100 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("t1-45")
        assert count == 1
        assert memory == 16 * _MIB_PER_GIB
        assert mfr == "NVIDIA"
        assert family == "Volta"
        assert model == "V100"

        # Test LE variant
        count, memory, _, _, _ = _get_gpu_info("t1-le-180")
        assert count == 4
        assert memory == 64 * _MIB_PER_GIB

    def test_rtx5000_instances(self):
        """Test RTX 5000 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("rtx5000-28")
        assert count == 1
        assert memory == 16 * _MIB_PER_GIB
        assert mfr == "NVIDIA"
        assert family == "Turing"
        assert model == "Quadro RTX 5000"

        count, memory, _, _, _ = _get_gpu_info("rtx5000-84")
        assert count == 3
        assert memory == 48 * _MIB_PER_GIB

    def test_non_gpu_instance(self):
        """Test non-GPU instance returns zeros and None."""
        count, memory, mfr, family, model = _get_gpu_info("b3-8")
        assert count == 0
        assert memory is None
        assert mfr is None
        assert family is None
        assert model is None

    def test_invalid_gpu_name(self):
        """Test invalid GPU instance name."""
        count, memory, mfr, family, model = _get_gpu_info("h100-invalid")
        assert count == 0
        assert memory is None


class TestInventoryComplianceFrameworks:
    """Tests for inventory_compliance_frameworks function."""

    def test_returns_list(self):
        """Test that function returns a list."""
        vendor = Mock()
        vendor.vendor_id = "ovh"
        result = inventory_compliance_frameworks(vendor)
        assert isinstance(result, list)

    @patch("sc_crawler.vendors._ovh.map_compliance_frameworks_to_vendor")
    def test_calls_mapping_function(self, mock_map):
        """Test that the function calls map_compliance_frameworks_to_vendor."""
        vendor = Mock()
        vendor.vendor_id = "ovh"
        mock_map.return_value = []

        inventory_compliance_frameworks(vendor)

        mock_map.assert_called_once_with("ovh", ["iso27001", "soc2t2"])


def test_inventory_regions():
    vendor = Mock()
    vendor.vendor_id = "ovh"
    result = inventory_regions(vendor)
    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["region_id"] == "EU-WEST-PAR"
    assert result[0]["city"] == "Paris"


def _zone(zone_id: str):
    return SimpleNamespace(zone_id=zone_id, status=Status.ACTIVE)


def _region(region_id: str, *, zones: list[str]):
    return SimpleNamespace(
        region_id=region_id,
        api_reference=region_id,
        zones=[_zone(z) for z in zones],
    )


def _ovh_vendor(*, regions=None, servers=None, databases=None, database_storages=None):
    vendor = Mock(vendor_id="ovh")
    vendor.regions = regions or [
        _region("GRA", zones=["gra-a"]),
        _region(
            "EU-WEST-PAR", zones=["eu-west-par-a", "eu-west-par-b", "eu-west-par-c"]
        ),
        _region("SGP", zones=["sgp-a"]),
    ]
    vendor.servers = servers or [
        SimpleNamespace(server_id="b3-8", api_reference="b3-8"),
    ]
    vendor.databases = databases or []
    vendor.database_storages = database_storages or []
    vendor.progress_tracker = Mock(
        start_task=Mock(), advance_task=Mock(), hide_task=Mock()
    )
    vendor.log = Mock()
    return vendor


def _pg_offer(
    *,
    plan="production",
    flavor="b3-8",
    region="GRA",
    version="16",
    min_nodes=2,
    max_nodes=2,
    min_disk=160,
    max_disk=480,
    retention_days=14,
    status="STABLE",
    engine="postgresql",
    network="public",
):
    plan_code = f"{engine}-{plan}-{flavor}.hour.consumption"
    return {
        "engine": engine,
        "version": version,
        "plan": plan,
        "flavor": flavor,
        "region": region,
        "planCode": plan_code,
        "planCodes": {"compute": plan_code},
        "backup": "automatic",
        "backupRetentionDays": retention_days,
        "backups": {"available": True, "retentionDays": retention_days},
        "minDiskSize": min_disk,
        "maxDiskSize": max_disk,
        "minNodeNumber": min_nodes,
        "maxNodeNumber": max_nodes,
        "network": network,
        "lifecycle": {"status": status, "startDate": "2024-01-01"},
        "status": status,
        "specifications": {
            "flavor": flavor,
            "network": network,
            "nodes": {"minimum": min_nodes, "maximum": max_nodes},
            "storage": {
                "minimum": {"unit": "GB", "value": min_disk},
                "maximum": {"unit": "GB", "value": max_disk},
            },
        },
    }


def _pg_capabilities():
    return {
        "engines": [
            {
                "name": "postgresql",
                "versions": ["14", "15", "16", "17"],
                "sslModes": ["required"],
            }
        ],
        "flavors": [
            {
                "name": "b3-8",
                "core": 2,
                "memory": 8,
                "storage": 160,
                "generation": "gen3",
                "specifications": {
                    "core": 2,
                    "memory": {"unit": "GB", "value": 8},
                    "storage": {"unit": "GB", "value": 160},
                },
            }
        ],
        "plans": [
            {
                "name": "essential",
                "backupRetention": "P2D",
                "description": "Essential",
            },
            {
                "name": "production",
                "backupRetention": "P14D",
                "description": "Production",
            },
        ],
    }


def _catalog_addon(plan_code: str, price_microcents: int):
    return {
        "planCode": plan_code,
        "pricings": [
            {
                "interval": 0,
                "capacities": ["consumption"],
                "price": price_microcents,
            }
        ],
    }


def _extend_ovh_get(mock_client, *, availability, capabilities, catalog_addons):
    original = mock_client.get.side_effect

    def fake_get(path, *args, **kwargs):
        if path.endswith("/database/availability"):
            return availability
        if path.endswith("/database/capabilities"):
            return capabilities
        if path == "/order/catalog/public/cloud":
            return {
                "locale": {"currencyCode": "EUR"},
                "addons": catalog_addons,
            }
        return original(path, *args, **kwargs)

    mock_client.get.side_effect = fake_get


def test_inventory_databases_collapses_versions_and_maps_fields(mock_ovh_client):
    availability = [
        _pg_offer(version="16", region="GRA"),
        _pg_offer(version="17", region="GRA"),
        _pg_offer(
            plan="essential",
            version="16",
            region="GRA",
            min_nodes=1,
            max_nodes=1,
            retention_days=2,
        ),
        _pg_offer(
            plan="discovery",
            version="16",
            region="GRA",
            min_nodes=1,
            max_nodes=1,
            retention_days=2,
        ),
        _pg_offer(engine="mysql", plan="production", version="8"),
        _pg_offer(version="16", region="GRA", status="UNAVAILABLE"),
        _pg_offer(
            plan="business",
            version="16",
            region="GRA",
            status="END_OF_LIFE",
        ),
    ]
    _extend_ovh_get(
        mock_ovh_client,
        availability=availability,
        capabilities=_pg_capabilities(),
        catalog_addons=[],
    )
    vendor = _ovh_vendor()
    rows = inventory_databases(vendor)
    by_id = {row["database_id"]: row for row in rows}
    assert set(by_id) == {
        "postgresql-production-b3-8",
        "postgresql-essential-b3-8",
        "postgresql-discovery-b3-8",
        "postgresql-business-b3-8",
    }

    production = by_id["postgresql-production-b3-8"]
    assert production["engine"] == DatabaseEngine.POSTGRESQL
    assert production["wire_protocol"] == DatabaseWireProtocol.POSTGRESQL
    assert production["engine_versions"] == ["16", "17"]
    assert production["family"] == "Production"
    assert production["name"] == "postgresql-production-b3-8"
    assert production["database_id"] == "postgresql-production-b3-8"
    assert production["vcpus"] == 2
    assert production["memory_amount"] == 8 * 1024
    assert production["storage_size"] == 160
    assert production["storage_extra_min"] == 0
    assert production["storage_extra_max"] == 320
    assert production["storage_extra_autosize"] is False
    assert production["server_id"] == "b3-8"
    assert production["api_reference"] == "postgresql-production-b3-8"
    assert production["api_reference_object"] == {
        "engine": "postgresql",
        "plan": "production",
        "flavor": "b3-8",
    }
    assert production["display_name"] == "Production b3-8"
    assert production["ha"] == [DatabaseHaLevel.SINGLE_ZONE]
    assert production["ha_strategy"] == [DatabaseHaStrategy.READABLE_CLUSTER]
    assert production["max_read_replicas"] == 1
    assert production["scheduled_backups"] is True
    assert production["continuous_backups"] == 14
    assert production["custom_config"] is True
    assert production["custom_extensions"] is True
    assert production["connection_pool"] is True
    assert production["disk_encryption"] is True
    assert production["sla"] == 99.9
    assert production["status"] == Status.ACTIVE
    assert DatabaseSecurityFeature.PRIVATE_NETWORK in production["security_features"]
    assert DatabaseSecurityFeature.AUDIT_LOGGING in production["security_features"]

    essential = by_id["postgresql-essential-b3-8"]
    assert essential["ha"] == [DatabaseHaLevel.NONE]
    assert essential["ha_strategy"] == [DatabaseHaStrategy.NONE]
    assert essential["max_read_replicas"] == 0
    assert essential["continuous_backups"] == 2
    assert essential["sla"] is None

    discovery = by_id["postgresql-discovery-b3-8"]
    assert discovery["ha"] == [DatabaseHaLevel.NONE]
    assert discovery["ha_strategy"] == [DatabaseHaStrategy.NONE]
    assert discovery["sla"] is None

    retired = by_id["postgresql-business-b3-8"]
    assert retired["status"] == Status.RETIRED


def test_inventory_databases_uses_availability_storage_not_flavor_nvme(mock_ovh_client):
    # capabilities.flavors[].storage is compute NVMe (100 GB for b3-16); DBaaS usable
    # disk is availability specifications.storage.minimum (320 GiB on pricing page).
    capabilities = {
        "engines": [
            {"name": "postgresql", "versions": ["16"], "sslModes": ["required"]}
        ],
        "flavors": [
            {
                "name": "b3-16",
                "core": 4,
                "memory": 16,
                "storage": 100,
                "generation": "gen3",
                "specifications": {
                    "core": 4,
                    "memory": {"unit": "GB", "value": 16},
                    "storage": {"unit": "GB", "value": 100},
                },
            }
        ],
        "plans": [{"name": "production", "backupRetention": "P14D"}],
    }
    _extend_ovh_get(
        mock_ovh_client,
        availability=[
            _pg_offer(
                flavor="b3-16",
                min_disk=320,
                max_disk=1600,
            )
        ],
        capabilities=capabilities,
        catalog_addons=[],
    )
    vendor = _ovh_vendor(
        servers=[SimpleNamespace(server_id="b3-16", api_reference="b3-16")]
    )
    rows = inventory_databases(vendor)
    assert len(rows) == 1
    assert rows[0]["database_id"] == "postgresql-production-b3-16"
    assert rows[0]["storage_size"] == 320
    assert rows[0]["storage_extra_max"] == 1280


def test_inventory_databases_merges_multi_az_ha(mock_ovh_client):
    availability = [
        _pg_offer(region="GRA", version="16"),
        _pg_offer(region="EU-WEST-PAR", version="16"),
    ]
    _extend_ovh_get(
        mock_ovh_client,
        availability=availability,
        capabilities=_pg_capabilities(),
        catalog_addons=[],
    )
    rows = inventory_databases(_ovh_vendor())
    assert len(rows) == 1
    assert rows[0]["ha"] == [
        DatabaseHaLevel.MULTI_ZONE,
        DatabaseHaLevel.SINGLE_ZONE,
    ]
    assert rows[0]["sla"] == 99.95


def test_inventory_database_prices_use_catalog_suffix_and_node_count(mock_ovh_client):
    availability = [
        _pg_offer(region="GRA", min_nodes=2),
        _pg_offer(region="EU-WEST-PAR", min_nodes=2),
        _pg_offer(region="SGP", min_nodes=2),
        _pg_offer(region="GRA", version="17", min_nodes=2),
    ]
    catalog_addons = [
        _catalog_addon(
            "databases.postgresql-production-b3-8.hour.consumption",
            10_000_000,
        ),
        _catalog_addon(
            "databases.postgresql-production-b3-8.hour.consumption.3az",
            12_000_000,
        ),
        _catalog_addon(
            "databases.postgresql-production-b3-8.hour.consumption.apac",
            15_000_000,
        ),
    ]
    _extend_ovh_get(
        mock_ovh_client,
        availability=availability,
        capabilities=_pg_capabilities(),
        catalog_addons=catalog_addons,
    )
    vendor = _ovh_vendor(
        databases=[SimpleNamespace(database_id="postgresql-production-b3-8")]
    )
    prices = inventory_database_prices(vendor)
    by_region = {row["region_id"]: row for row in prices}
    assert set(by_region) == {"GRA", "EU-WEST-PAR", "SGP"}

    gra = by_region["GRA"]
    assert gra["allocation"] == Allocation.ONDEMAND
    assert gra["unit"] == PriceUnit.HOUR
    assert gra["currency"] == "EUR"
    assert gra["ha"] == DatabaseHaLevel.SINGLE_ZONE
    assert gra["ha_strategy"] == DatabaseHaStrategy.READABLE_CLUSTER
    assert gra["price"] == pytest.approx(0.2)

    par = by_region["EU-WEST-PAR"]
    assert par["ha"] == DatabaseHaLevel.MULTI_ZONE
    assert par["price"] == pytest.approx(0.24)

    sgp = by_region["SGP"]
    assert sgp["ha"] == DatabaseHaLevel.SINGLE_ZONE
    assert sgp["price"] == pytest.approx(0.3)


def test_inventory_database_prices_skip_unknown_region(mock_ovh_client):
    _extend_ovh_get(
        mock_ovh_client,
        availability=[_pg_offer(region="UNKNOWN")],
        capabilities=_pg_capabilities(),
        catalog_addons=[
            _catalog_addon(
                "databases.postgresql-production-b3-8.hour.consumption",
                10_000_000,
            )
        ],
    )
    vendor = _ovh_vendor(
        databases=[SimpleNamespace(database_id="postgresql-production-b3-8")]
    )
    assert inventory_database_prices(vendor) == []
    vendor.log.assert_called()


def test_inventory_database_storages_additional_disk_bounds(mock_ovh_client):
    availability = [
        _pg_offer(region="GRA", min_disk=160, max_disk=800),
        _pg_offer(region="EU-WEST-PAR", min_disk=160, max_disk=1600),
        _pg_offer(
            plan="essential",
            min_nodes=1,
            max_nodes=1,
            min_disk=80,
            max_disk=80,
        ),
        _pg_offer(engine="mysql", plan="production", min_disk=100, max_disk=500),
    ]
    _extend_ovh_get(
        mock_ovh_client,
        availability=availability,
        capabilities=_pg_capabilities(),
        catalog_addons=[],
    )
    rows = inventory_database_storages(_ovh_vendor())
    by_id = {row["database_storage_id"]: row for row in rows}
    assert set(by_id) == {"postgresql-production-additional"}
    production = by_id["postgresql-production-additional"]
    assert production["scope"] == DatabaseStorageScope.DATA
    assert production["min_size"] == 0
    assert production["max_size"] == 1440


def test_inventory_database_storage_prices_use_catalog_suffix(mock_ovh_client):
    availability = [
        _pg_offer(region="GRA"),
        _pg_offer(region="EU-WEST-PAR"),
        _pg_offer(region="SGP"),
        _pg_offer(region="GRA", version="17"),
    ]
    catalog_addons = [
        _catalog_addon(
            "databases.postgresql-production-additionnal-storage-gb.hour.consumption",
            60_000,
        ),
        _catalog_addon(
            "databases.postgresql-production-additionnal-storage-gb.hour.consumption.3az",
            60_000,
        ),
        _catalog_addon(
            "databases.postgresql-production-additionnal-storage-gb.hour.consumption.apac",
            70_000,
        ),
    ]
    _extend_ovh_get(
        mock_ovh_client,
        availability=availability,
        capabilities=_pg_capabilities(),
        catalog_addons=catalog_addons,
    )
    vendor = _ovh_vendor(
        database_storages=[
            SimpleNamespace(database_storage_id="postgresql-production-additional")
        ]
    )
    prices = inventory_database_storage_prices(vendor)
    by_region = {row["region_id"]: row for row in prices}
    assert set(by_region) == {"GRA", "EU-WEST-PAR", "SGP"}
    gra = by_region["GRA"]
    assert gra["database_storage_id"] == "postgresql-production-additional"
    assert gra["unit"] == PriceUnit.GB_MONTH
    assert gra["currency"] == "EUR"
    assert gra["price"] == pytest.approx(0.0006 * 730)
    assert by_region["EU-WEST-PAR"]["price"] == pytest.approx(0.0006 * 730)
    assert by_region["SGP"]["price"] == pytest.approx(0.0007 * 730)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
