"""Unit tests for OVHcloud vendor module."""

from unittest.mock import Mock, patch

import pytest

from sc_crawler.table_fields import (
    Allocation,
    CpuAllocation,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)
from sc_crawler.vendors.ovh import (
    CURRENCY,
    HOURS_PER_MONTH,
    MIB_PER_GIB,
    MICROCENTS_PER_CURRENCY_UNIT,
    _get_base_region_and_city,
    _get_cpu_info,
    _get_gpu_info,
    _get_regions_from_catalog,
    _get_server_family,
    _get_servers_from_catalog,
    _get_storage_type,
    _get_storages_from_catalog,
    inventory_compliance_frameworks,
    inventory_ipv4_prices,
    inventory_regions,
    inventory_server_prices,
    inventory_server_prices_spot,
    inventory_servers,
    inventory_storage_prices,
    inventory_storages,
    inventory_traffic_prices,
    inventory_zones,
)


class TestConstants:
    """Test module-level constants."""

    def test_constants_values(self):
        """Test that constants have expected values."""
        assert HOURS_PER_MONTH == 730
        assert MICROCENTS_PER_CURRENCY_UNIT == 100_000_000
        assert MIB_PER_GIB == 1024
        assert CURRENCY == "USD"


class TestGetBaseRegionAndCity:
    """Tests for _get_base_region_and_city function."""

    def test_simple_region_code(self):
        """Test simple region codes without numbers."""
        base, city = _get_base_region_and_city("GRA")
        assert base == "GRA"
        assert city == "Gravelines"

    def test_region_code_with_number(self):
        """Test region codes with zone numbers."""
        base, city = _get_base_region_and_city("GRA9")
        assert base == "GRA"
        assert city == "Gravelines"

        base, city = _get_base_region_and_city("BHS5")
        assert base == "BHS"
        assert city == "Montreal"

    def test_region_code_with_descriptive_format(self):
        """Test descriptive region codes like CA-EAST-TOR."""
        base, city = _get_base_region_and_city("CA-EAST-TOR")
        assert base == "TOR"
        assert city == "Toronto"

        base, city = _get_base_region_and_city("EU-WEST-PAR")
        assert base == "PAR"
        assert city == "Paris"

    def test_region_code_special_format(self):
        """Test special formats like RBX-ARCHIVE."""
        base, city = _get_base_region_and_city("RBX-ARCHIVE")
        assert base == "RBX"
        assert city == "Roubaix"

        base, city = _get_base_region_and_city("RBX-A")
        assert base == "RBX"
        assert city == "Roubaix"

    def test_unknown_region_code(self):
        """Test region code not in mapping returns None for city."""
        base, city = _get_base_region_and_city("UNKNOWN")
        assert base == "UNKNOWN"
        assert city is None


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


class TestGetCpuInfo:
    """Tests for _get_cpu_info function."""

    def test_b3_series_cpu(self):
        """Test B3 series CPU info."""
        manufacturer, model, speed = _get_cpu_info("b3-8")
        assert manufacturer == "AMD"
        assert model == "EPYC Milan"
        assert speed == 2.3

    def test_c3_series_cpu(self):
        """Test C3 series CPU info."""
        manufacturer, model, speed = _get_cpu_info("c3-32")
        assert manufacturer is None
        assert model is None
        assert speed == 2.3

    def test_c2_series_cpu(self):
        """Test C2 series CPU info."""
        manufacturer, model, speed = _get_cpu_info("c2-60")
        assert manufacturer is None
        assert model is None
        assert speed == 3.0

    def test_r2_series_cpu(self):
        """Test R2 series CPU info."""
        manufacturer, model, speed = _get_cpu_info("r2-120")
        assert manufacturer is None
        assert model is None
        assert speed == 2.2

    def test_bare_metal_cpu(self):
        """Test Bare Metal CPU info."""
        _, _, speed = _get_cpu_info("bm-s1")
        assert speed == 4.0

        _, _, speed = _get_cpu_info("bm-m1")
        assert speed == 3.7

        _, _, speed = _get_cpu_info("bm-l1")
        assert speed == 3.1

    def test_gpu_instance_cpu(self):
        """Test GPU instance CPU info."""
        _, _, speed = _get_cpu_info("a10-45")
        assert speed == 3.3

        _, _, speed = _get_cpu_info("h100-380")
        assert speed == 3.0

        _, _, speed = _get_cpu_info("t1-45")
        assert speed == 3.0

    def test_unknown_flavor(self):
        """Test unknown flavor returns None values."""
        manufacturer, model, speed = _get_cpu_info("unknown-flavor")
        assert manufacturer is None
        assert model is None
        assert speed is None


class TestGetGpuInfo:
    """Tests for _get_gpu_info function."""

    def test_h100_instances(self):
        """Test H100 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("h100-380")
        assert count == 1
        assert memory == 80
        assert mfr == "NVIDIA"
        assert family == "Hopper"
        assert model == "H100 80GB HBM3"

        count, memory, _, _, _ = _get_gpu_info("h100-760")
        assert count == 2
        assert memory == 160

    def test_a100_instances(self):
        """Test A100 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("a100-180")
        assert count == 1
        assert memory == 80
        assert mfr == "NVIDIA"
        assert family == "Ampere"
        assert model == "A100 80GB HBM2e"

    def test_a10_instances(self):
        """Test A10 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("a10-45")
        assert count == 1
        assert memory == 24
        assert mfr == "NVIDIA"
        assert family == "Ampere"
        assert model == "A10 24GB GDDR6"

        count, memory, _, _, _ = _get_gpu_info("a10-180")
        assert count == 4
        assert memory == 96

    def test_l40s_instances(self):
        """Test L40S GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("l40s-90")
        assert count == 1
        assert memory == 48
        assert mfr == "NVIDIA"
        assert family == "Ada Lovelace"
        assert model == "L40S 48GB GDDR6"

    def test_l4_instances(self):
        """Test L4 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("l4-90")
        assert count == 1
        assert memory == 24
        assert mfr == "NVIDIA"
        assert family == "Ada Lovelace"
        assert model == "L4 24GB GDDR6"

    def test_v100s_instances(self):
        """Test V100S GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("t2-45")
        assert count == 1
        assert memory == 32
        assert mfr == "NVIDIA"
        assert family == "Volta"
        assert model == "Tesla V100S 32GB HBM2"

        # Test LE variant
        count, memory, _, _, _ = _get_gpu_info("t2-le-90")
        assert count == 2
        assert memory == 64

    def test_v100_instances(self):
        """Test V100 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("t1-45")
        assert count == 1
        assert memory == 16
        assert mfr == "NVIDIA"
        assert family == "Volta"
        assert model == "Tesla V100 16GB HBM2"

        # Test LE variant
        count, memory, _, _, _ = _get_gpu_info("t1-le-180")
        assert count == 4
        assert memory == 64

    def test_rtx5000_instances(self):
        """Test RTX 5000 GPU instances."""
        count, memory, mfr, family, model = _get_gpu_info("rtx5000-28")
        assert count == 1
        assert memory == 16
        assert mfr == "NVIDIA"
        assert family == "Turing"
        assert model == "Quadro RTX 5000 16GB GDDR6"

        count, memory, _, _, _ = _get_gpu_info("rtx5000-84")
        assert count == 3
        assert memory == 48

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


class TestGetStorageType:
    """Tests for _get_storage_type function."""

    def test_b3_series_storage(self):
        """Test B3 series storage type (NVMe)."""
        assert _get_storage_type("b3-8") == StorageType.NVME_SSD

    def test_c3_series_storage(self):
        """Test C3 series storage type (NVMe)."""
        assert _get_storage_type("c3-32") == StorageType.NVME_SSD

    def test_r3_series_storage(self):
        """Test R3 series storage type (NVMe)."""
        assert _get_storage_type("r3-64") == StorageType.NVME_SSD

    def test_d2_series_storage(self):
        """Test D2 series storage type (NVMe)."""
        assert _get_storage_type("d2-8") == StorageType.NVME_SSD

    def test_b2_series_storage(self):
        """Test B2 series storage type (SATA SSD)."""
        assert _get_storage_type("b2-30") == StorageType.SSD

    def test_c2_series_storage(self):
        """Test C2 series storage type (SATA SSD)."""
        assert _get_storage_type("c2-60") == StorageType.SSD

    def test_bare_metal_storage(self):
        """Test Bare Metal storage type (SATA SSD)."""
        assert _get_storage_type("bm-m1") == StorageType.SSD

    def test_gpu_nvme_storage(self):
        """Test GPU instances with NVMe storage."""
        assert _get_storage_type("t1-45") == StorageType.NVME_SSD
        assert _get_storage_type("h100-760") == StorageType.NVME_SSD
        assert _get_storage_type("l4-90") == StorageType.NVME_SSD

    def test_gpu_ssd_storage(self):
        """Test GPU instances with SATA SSD storage."""
        assert _get_storage_type("rtx5000-28") == StorageType.SSD

    def test_i1_storage(self):
        """Test I1 series storage type (mixed, returns SSD)."""
        assert _get_storage_type("i1-90") == StorageType.SSD

    def test_default_storage(self):
        """Test unknown instance defaults to SSD."""
        assert _get_storage_type("unknown-instance") == StorageType.SSD


class TestInventoryComplianceFrameworks:
    """Tests for inventory_compliance_frameworks function."""

    def test_returns_list(self):
        """Test that function returns a list."""
        vendor = Mock()
        vendor.vendor_id = "ovh"
        result = inventory_compliance_frameworks(vendor)
        assert isinstance(result, list)

    @patch("sc_crawler.vendors.ovh.map_compliance_frameworks_to_vendor")
    def test_calls_mapping_function(self, mock_map):
        """Test that the function calls map_compliance_frameworks_to_vendor."""
        vendor = Mock()
        vendor.vendor_id = "ovh"
        mock_map.return_value = []

        inventory_compliance_frameworks(vendor)

        mock_map.assert_called_once_with("ovh", ["iso27001", "soc2t2"])


class TestInventoryRegions:
    """Tests for inventory_regions function."""

    @patch("sc_crawler.vendors.ovh._get_regions_from_catalog")
    def test_basic_region_structure(self, mock_get_regions):
        """Test basic region data structure."""
        mock_get_regions.return_value = ["GRA9", "BHS5"]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_regions(vendor)

        assert len(result) == 2
        assert result[0]["vendor_id"] == "ovh"
        assert result[0]["region_id"] == "GRA9"
        assert result[0]["name"] == "GRA9"
        assert result[0]["city"] == "Gravelines"
        assert result[0]["country_id"] == "FR"

    @patch("sc_crawler.vendors.ovh._get_regions_from_catalog")
    def test_region_with_coordinates(self, mock_get_regions):
        """Test region includes coordinates."""
        mock_get_regions.return_value = ["SBG"]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_regions(vendor)

        assert result[0]["lon"] is not None
        assert result[0]["lat"] is not None
        assert isinstance(result[0]["lon"], float)
        assert isinstance(result[0]["lat"], float)

    @patch("sc_crawler.vendors.ovh._get_regions_from_catalog")
    def test_region_with_address(self, mock_get_regions):
        """Test region includes address information."""
        mock_get_regions.return_value = ["SBG"]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_regions(vendor)

        assert result[0]["address_line"] is not None
        assert "Strasbourg" in result[0]["address_line"]
        assert result[0]["zip_code"] == "67000"

    @patch("sc_crawler.vendors.ovh._get_regions_from_catalog")
    def test_north_america_region_has_state(self, mock_get_regions):
        """Test North American regions include state/province."""
        mock_get_regions.return_value = ["BHS"]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_regions(vendor)

        assert result[0]["state"] == "Quebec"
        assert result[0]["country_id"] == "CA"


class TestInventoryZones:
    """Tests for inventory_zones function."""

    @patch("sc_crawler.vendors.ovh._get_regions_from_catalog")
    def test_zones_match_regions(self, mock_get_regions):
        """Test that zones are created 1:1 with regions."""
        mock_get_regions.return_value = ["GRA9", "BHS5"]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_zones(vendor)

        assert len(result) == 2
        assert result[0]["zone_id"] == "GRA9"
        assert result[0]["region_id"] == "GRA9"
        assert result[0]["name"] == "Gravelines"


class TestInventoryServers:
    """Tests for inventory_servers function."""

    @patch("sc_crawler.vendors.ovh._get_servers_from_catalog")
    def test_basic_server_structure(self, mock_get_servers):
        """Test basic server data structure."""
        mock_get_servers.return_value = [
            {
                "invoiceName": "b3-8",
                "blobs": {
                    "commercial": {"name": "b3-8", "brickSubtype": "General Purpose"},
                    "technical": {
                        "cpu": {"cores": 2, "frequency": 2.3, "type": "shared"},
                        "memory": {"size": 8},
                        "bandwidth": {"level": 500},
                        "storage": {
                            "disks": [
                                {"number": 1, "capacity": 50, "technology": "nvme"}
                            ]
                        },
                    },
                    "tags": ["active"],
                },
            }
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_servers(vendor)

        assert len(result) == 1
        server = result[0]
        assert server["server_id"] == "b3-8"
        assert server["vendor_id"] == "ovh"
        assert server["vcpus"] == 2
        assert server["memory_amount"] == 8 * 1024  # Convert to MiB
        assert server["storage_size"] == 50
        assert server["cpu_allocation"] == CpuAllocation.SHARED
        assert server["status"] == Status.ACTIVE

    @patch("sc_crawler.vendors.ovh._get_servers_from_catalog")
    def test_server_with_gpu(self, mock_get_servers):
        """Test server with GPU information."""
        mock_get_servers.return_value = [
            {
                "invoiceName": "h100-380",
                "blobs": {
                    "commercial": {"name": "h100-380", "brickSubtype": "GPU Instance"},
                    "technical": {
                        "cpu": {"cores": 30, "frequency": 3.0, "type": "shared"},
                        "memory": {"size": 380},
                        "gpu": {
                            "number": 1,
                            "model": "H100",
                            "memory": {"size": 80, "interface": "HBM3"},
                        },
                        "bandwidth": {"level": 8000},
                        "storage": {
                            "disks": [
                                {"number": 1, "capacity": 200, "technology": "nvme"}
                            ]
                        },
                    },
                    "tags": ["active"],
                },
            }
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_servers(vendor)

        assert len(result) == 1
        server = result[0]
        assert server["gpu_count"] == 1
        assert server["gpu_memory_total"] == 80 * 1024  # Convert to MiB
        assert server["gpu_manufacturer"] == "NVIDIA"
        assert server["gpu_family"] == "Hopper"

    @patch("sc_crawler.vendors.ovh._get_servers_from_catalog")
    def test_server_deduplication(self, mock_get_servers):
        """Test that duplicate server names are deduplicated."""
        mock_get_servers.return_value = [
            {
                "invoiceName": "b3-8",
                "blobs": {
                    "commercial": {"name": "b3-8", "brickSubtype": "GP"},
                    "technical": {
                        "cpu": {"cores": 2, "type": "shared"},
                        "memory": {"size": 8},
                        "bandwidth": {"level": 500},
                        "storage": {"disks": [{"number": 1, "capacity": 50}]},
                    },
                    "tags": ["active"],
                },
            },
            {
                "invoiceName": "b3-8",  # Duplicate
                "blobs": {
                    "commercial": {"name": "b3-8", "brickSubtype": "GP"},
                    "technical": {
                        "cpu": {"cores": 2, "type": "shared"},
                        "memory": {"size": 8},
                        "bandwidth": {"level": 500},
                        "storage": {"disks": [{"number": 1, "capacity": 50}]},
                    },
                    "tags": ["active"],
                },
            },
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_servers(vendor)

        assert len(result) == 1  # Duplicates removed


class TestInventoryServerPrices:
    """Tests for inventory_server_prices function."""

    @patch("sc_crawler.vendors.ovh._get_flavors")
    @patch("sc_crawler.vendors.ovh._client")
    @patch("sc_crawler.vendors.ovh._get_servers_from_catalog")
    def test_basic_pricing_structure(
        self, mock_get_servers, mock_client, mock_get_flavors
    ):
        """Test basic server pricing data structure.

        Note: We need both hourly and monthly plans in the mock data because
        regions are only available in monthly plans. Regions are merged from
        all pricing variants but only hourly plans are actually processed
        (monthly plans are skipped to avoid primary key conflicts).
        """
        mock_get_flavors.return_value = []  # Fallback not needed in this test
        mock_get_servers.return_value = [
            # Monthly plan (has regions)
            {
                "planCode": "b3-8.monthly.postpaid",
                "invoiceName": "b3-8",
                "configurations": [{"name": "region", "values": ["GRA9", "BHS5"]}],
                "pricings": [
                    {
                        "price": 36500000000,  # microcents per month
                        "intervalUnit": "month",
                    }
                ],
                "blobs": {
                    "commercial": {"name": "b3-8"},
                    "technical": {"os": {"family": "linux"}},
                    "tags": ["active"],
                },
            },
            # Hourly plan (no regions, will use regions from monthly plan)
            {
                "planCode": "b3-8.consumption",
                "invoiceName": "b3-8",
                "configurations": [],  # Hourly plans don't have region info
                "pricings": [
                    {
                        "price": 5080000,  # microcents
                        "intervalUnit": "hour",
                    }
                ],
                "blobs": {
                    "commercial": {"name": "b3-8"},
                    "technical": {"os": {"family": "linux"}},
                    "tags": ["active"],
                },
            },
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_server_prices(vendor)

        # Only hourly plans are processed (monthly plans are skipped to avoid primary key conflicts)
        assert len(result) == 2  # 2 regions × 1 pricing plan (hourly only)

        # All entries should be hourly pricing
        assert all(p["unit"] == PriceUnit.HOUR for p in result)

        price = result[0]
        assert price["vendor_id"] == "ovh"
        assert price["server_id"] == "b3-8"
        assert price["region_id"] in ["GRA9", "BHS5"]
        assert price["unit"] == PriceUnit.HOUR
        assert price["price"] == pytest.approx(5080000 / MICROCENTS_PER_CURRENCY_UNIT)
        assert price["currency"] == CURRENCY
        assert price["allocation"] == Allocation.ONDEMAND
        assert price["status"] == Status.ACTIVE

    @patch("sc_crawler.vendors.ovh._get_flavors")
    @patch("sc_crawler.vendors.ovh._client")
    @patch("sc_crawler.vendors.ovh._get_servers_from_catalog")
    def test_monthly_pricing_skipped(
        self, mock_get_servers, mock_client, mock_get_flavors
    ):
        """Test that monthly pricing plans are skipped (only hourly plans processed)."""
        mock_get_flavors.return_value = []  # Fallback not needed in this test
        mock_get_servers.return_value = [
            {
                "planCode": "b3-8.monthly.postpaid",
                "invoiceName": "b3-8",
                "configurations": [{"name": "region", "values": ["GRA9"]}],
                "pricings": [
                    {
                        "price": 36500000000,  # microcents per month
                        "intervalUnit": "month",
                    }
                ],
                "blobs": {
                    "commercial": {"name": "b3-8"},
                    "technical": {"os": {"family": "linux"}},
                    "tags": ["active"],
                },
            }
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_server_prices(vendor)

        # Monthly plans should be skipped
        assert len(result) == 0

    @patch("sc_crawler.vendors.ovh._get_flavors")
    @patch("sc_crawler.vendors.ovh._client")
    @patch("sc_crawler.vendors.ovh._get_servers_from_catalog")
    def test_skip_local_zone_variants(
        self, mock_get_servers, mock_client, mock_get_flavors
    ):
        """Test that Local Zone variants are skipped."""
        mock_get_flavors.return_value = []  # Fallback not needed in this test
        mock_get_servers.return_value = [
            {
                "planCode": "b3-8.consumption.LZ.EU",
                "invoiceName": "b3-8",
                "configurations": [{"name": "region", "values": ["GRA9"]}],
                "pricings": [{"price": 5080000, "intervalUnit": "hour"}],
                "blobs": {
                    "commercial": {"name": "b3-8"},
                    "technical": {"os": {"family": "linux"}},
                    "tags": ["active"],
                },
            },
            {
                "planCode": "b3-8.consumption.3AZ",
                "invoiceName": "b3-8",
                "configurations": [{"name": "region", "values": ["PAR"]}],
                "pricings": [{"price": 5080000, "intervalUnit": "hour"}],
                "blobs": {
                    "commercial": {"name": "b3-8"},
                    "technical": {"os": {"family": "linux"}},
                    "tags": ["active"],
                },
            },
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_server_prices(vendor)

        assert len(result) == 0  # All skipped

    @patch("sc_crawler.vendors.ovh._get_flavors")
    @patch("sc_crawler.vendors.ovh._client")
    @patch("sc_crawler.vendors.ovh._get_servers_from_catalog")
    def test_fallback_to_flavors_api(
        self, mock_get_servers, mock_client, mock_get_flavors
    ):
        """Test fallback to flavors API when catalog has no regions."""
        mock_get_servers.return_value = [
            {
                "planCode": "b3-8.consumption",
                "invoiceName": "b3-8",
                "configurations": [],  # No regions in catalog
                "pricings": [{"price": 5080000, "intervalUnit": "hour"}],
                "blobs": {
                    "commercial": {"name": "b3-8"},
                    "technical": {"os": {"family": "linux"}},
                    "tags": ["active"],
                },
            }
        ]
        # Mock flavors API to return regions
        mock_get_flavors.return_value = [
            {"region": "GRA9", "planCodes": {"hourly": "b3-8.consumption"}},
            {"region": "BHS5", "planCodes": {"hourly": "b3-8.consumption"}},
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_server_prices(vendor)

        # Should have 2 entries from flavors API fallback
        assert len(result) == 2
        assert all(p["unit"] == PriceUnit.HOUR for p in result)
        regions = {p["region_id"] for p in result}
        assert regions == {"GRA9", "BHS5"}

    @patch("sc_crawler.vendors.ovh._get_flavors")
    @patch("sc_crawler.vendors.ovh._client")
    @patch("sc_crawler.vendors.ovh._get_servers_from_catalog")
    def test_skip_when_no_regions_anywhere(
        self, mock_get_servers, mock_client, mock_get_flavors
    ):
        """Test that servers with no regions in catalog or flavors API are skipped."""
        mock_get_servers.return_value = [
            {
                "planCode": "b3-8.consumption",
                "invoiceName": "b3-8",
                "configurations": [],  # No regions in catalog
                "pricings": [{"price": 5080000, "intervalUnit": "hour"}],
                "blobs": {
                    "commercial": {"name": "b3-8"},
                    "technical": {"os": {"family": "linux"}},
                    "tags": ["active"],
                },
            }
        ]
        # Mock flavors API to return no matching regions
        mock_get_flavors.return_value = [
            {
                "region": "GRA9",
                "planCodes": {
                    "hourly": "different-server.consumption"
                },  # Different server
            }
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_server_prices(vendor)

        # Should have 0 entries - server skipped due to no regions
        assert len(result) == 0


class TestInventoryServerPricesSpot:
    """Tests for inventory_server_prices_spot function."""

    def test_returns_empty_list(self):
        """Test that spot prices return empty list (no spot instances)."""
        vendor = Mock()
        result = inventory_server_prices_spot(vendor)
        assert result == []


class TestInventoryStorages:
    """Tests for inventory_storages function."""

    @patch("sc_crawler.vendors.ovh._get_storages_from_catalog")
    def test_block_storage(self, mock_get_storages):
        """Test block storage (volume) extraction."""
        mock_get_storages.return_value = [
            {
                "invoiceName": "volume.high-speed",
                "blobs": {
                    "commercial": {
                        "brick": "volume",
                        "brickSubtype": "block storage",
                        "name": "volume.high-speed",
                    },
                    "technical": {
                        "volume": {
                            "capacity": {"max": 12000},
                            "iops": {"guaranteed": False, "level": 3000},
                        }
                    },
                },
            }
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_storages(vendor)

        assert len(result) == 1
        storage = result[0]
        assert storage["storage_id"] == "volume.high-speed"
        assert storage["vendor_id"] == "ovh"
        assert storage["name"] == "block storage"
        assert storage["storage_type"] == StorageType.NETWORK
        assert storage["max_iops"] == 3000
        assert storage["max_size"] == 12000

    @patch("sc_crawler.vendors.ovh._get_storages_from_catalog")
    def test_object_storage(self, mock_get_storages):
        """Test object storage extraction."""
        mock_get_storages.return_value = [
            {
                "invoiceName": "storage",
                "blobs": {
                    "commercial": {
                        "brick": "storage",
                        "brickSubtype": "Object Storage",
                        "name": "storage-replicated",
                    },
                    "technical": {},
                },
            }
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_storages(vendor)

        assert len(result) == 1
        storage = result[0]
        assert storage["name"] == "Object Storage"
        assert storage["max_iops"] is None

    @patch("sc_crawler.vendors.ovh._get_storages_from_catalog")
    def test_storage_name_with_spaces(self, mock_get_storages):
        """Test storage name with spaces gets replaced."""
        mock_get_storages.return_value = [
            {
                "invoiceName": "bandwidth_storage in",
                "blobs": {
                    "commercial": {
                        "brick": "storage",
                        "brickSubtype": "Object Storage",
                        "name": "bandwidth-storage-in",
                    },
                    "technical": {},
                },
            }
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_storages(vendor)

        assert result[0]["storage_id"] == "bandwidth_storage_in"


class TestInventoryStoragePrices:
    """Tests for inventory_storage_prices function."""

    @patch("sc_crawler.vendors.ovh._get_storages_from_catalog")
    def test_hourly_pricing_conversion(self, mock_get_storages):
        """Test hourly pricing gets converted to monthly."""
        mock_get_storages.return_value = [
            {
                "planCode": "volume.high-speed.consumption",
                "invoiceName": "volume.high-speed",
                "configurations": [{"name": "region", "values": ["GRA9", "BHS5"]}],
                "pricings": [
                    {
                        "price": 13200,  # microcents per hour
                        "description": "hourly prices",
                    }
                ],
                "blobs": {
                    "commercial": {"brick": "volume", "name": "volume.high-speed"},
                    "technical": {},
                },
            }
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_storage_prices(vendor)

        assert len(result) == 2
        price_entry = result[0]
        expected_monthly_price = (
            13200 * HOURS_PER_MONTH
        ) / MICROCENTS_PER_CURRENCY_UNIT
        assert price_entry["price"] == pytest.approx(expected_monthly_price)
        assert price_entry["unit"] == PriceUnit.GB_MONTH

    @patch("sc_crawler.vendors.ovh._get_storages_from_catalog")
    def test_monthly_pricing_no_conversion(self, mock_get_storages):
        """Test monthly pricing doesn't get multiplied again."""
        mock_get_storages.return_value = [
            {
                "planCode": "volume.classic.monthly.postpaid",
                "invoiceName": "volume.classic",
                "configurations": [{"name": "region", "values": ["GRA9"]}],
                "pricings": [
                    {
                        "price": 4800000,  # microcents per month
                        "description": "monthly prices",
                    }
                ],
                "blobs": {
                    "commercial": {"brick": "volume", "name": "volume.classic"},
                    "technical": {},
                },
            }
        ]
        vendor = Mock()
        vendor.vendor_id = "ovh"

        result = inventory_storage_prices(vendor)

        expected_price = 4800000 / MICROCENTS_PER_CURRENCY_UNIT
        assert result[0]["price"] == pytest.approx(expected_price)


class TestInventoryTrafficPrices:
    """Tests for inventory_traffic_prices function."""

    def test_inbound_traffic_free(self):
        """Test inbound traffic is free everywhere."""
        vendor = Mock()
        vendor.vendor_id = "ovh"
        vendor.regions = [Mock(region_id="GRA9"), Mock(region_id="SGP1")]

        result = inventory_traffic_prices(vendor)

        inbound_prices = [p for p in result if p["direction"] == TrafficDirection.IN]
        assert len(inbound_prices) == 2
        for price in inbound_prices:
            assert price["price"] == 0
            assert price["price_tiered"] == []

    def test_outbound_traffic_free_non_apac(self):
        """Test outbound traffic is free in non-APAC regions."""
        vendor = Mock()
        vendor.vendor_id = "ovh"
        vendor.regions = [Mock(region_id="GRA9")]

        result = inventory_traffic_prices(vendor)

        outbound = [p for p in result if p["direction"] == TrafficDirection.OUT][0]
        assert outbound["price"] == 0
        assert outbound["price_tiered"] == []

    def test_outbound_traffic_tiered_apac(self):
        """Test outbound traffic has tiered pricing in APAC regions."""
        vendor = Mock()
        vendor.vendor_id = "ovh"
        vendor.regions = [
            Mock(region_id="SGP1"),
            Mock(region_id="SYD1"),
            Mock(region_id="MUM"),
        ]

        result = inventory_traffic_prices(vendor)

        outbound_prices = [p for p in result if p["direction"] == TrafficDirection.OUT]
        assert len(outbound_prices) == 3

        for price in outbound_prices:
            assert price["price"] == pytest.approx(0.0109)
            assert len(price["price_tiered"]) == 2
            assert price["price_tiered"][0]["lower"] == 1
            assert price["price_tiered"][0]["upper"] == 1024
            assert price["price_tiered"][0]["price"] == 0
            assert price["price_tiered"][1]["lower"] == 1025
            assert price["price_tiered"][1]["upper"] == "Infinity"
            assert price["price_tiered"][1]["price"] == pytest.approx(0.0109)

    def test_traffic_price_structure(self):
        """Test traffic price data structure."""
        vendor = Mock()
        vendor.vendor_id = "ovh"
        vendor.regions = [Mock(region_id="GRA9")]

        result = inventory_traffic_prices(vendor)

        for price in result:
            assert "vendor_id" in price
            assert "region_id" in price
            assert "price" in price
            assert "price_tiered" in price
            assert "currency" in price
            assert "unit" in price
            assert "direction" in price
            assert price["currency"] == CURRENCY
            assert price["unit"] == PriceUnit.GB_MONTH


class TestInventoryIpv4Prices:
    """Tests for inventory_ipv4_prices function."""

    def test_ipv4_included_by_default(self):
        """Test IPv4 is included (free) by default."""
        vendor = Mock()
        vendor.vendor_id = "ovh"
        vendor.regions = [Mock(region_id="GRA9"), Mock(region_id="BHS5")]

        result = inventory_ipv4_prices(vendor)

        assert len(result) == 2
        for price in result:
            assert price["price"] == 0
            assert price["currency"] == CURRENCY
            assert price["unit"] == PriceUnit.MONTH

    def test_ipv4_price_structure(self):
        """Test IPv4 price data structure."""
        vendor = Mock()
        vendor.vendor_id = "ovh"
        vendor.regions = [Mock(region_id="GRA9")]

        result = inventory_ipv4_prices(vendor)

        assert "vendor_id" in result[0]
        assert "region_id" in result[0]
        assert "price" in result[0]
        assert "currency" in result[0]
        assert "unit" in result[0]


class TestCatalogHelpers:
    """Tests for catalog helper functions."""

    @patch("sc_crawler.vendors.ovh._get_catalog")
    @patch("sc_crawler.vendors.ovh._client")
    def test_get_servers_from_catalog(self, mock_client, mock_get_catalog):
        """Test server extraction from catalog."""
        mock_get_catalog.return_value = {
            "plans": [
                {
                    "planCode": "project",
                    "addonFamilies": [
                        {
                            "name": "instance",
                            "addons": ["b3-8.consumption", "win-b3-8.consumption"],
                        }
                    ],
                }
            ],
            "addons": [
                {
                    "planCode": "b3-8.consumption",
                    "invoiceName": "b3-8",
                    "blobs": {"commercial": {"name": "b3-8"}},
                },
                {
                    "planCode": "win-b3-8.consumption",
                    "invoiceName": "win-b3-8",
                    "blobs": {"commercial": {"name": "win-b3-8"}},
                },
            ],
        }

        result = _get_servers_from_catalog()

        # Should exclude Windows instances
        assert len(result) == 1
        assert result[0]["planCode"] == "b3-8.consumption"

    @patch("sc_crawler.vendors.ovh._get_servers_from_catalog")
    def test_get_regions_from_catalog(self, mock_get_servers):
        """Test region extraction from catalog with merged pricing variants."""
        mock_get_servers.return_value = [
            {
                "invoiceName": "b3-8",
                "planCode": "b3-8.consumption",
                "configurations": [],  # Hourly plan with no regions
            },
            {
                "invoiceName": "b3-8",
                "planCode": "b3-8.monthly.postpaid",
                "configurations": [
                    {"name": "region", "values": ["GRA9", "BHS5", "SGP1"]}
                ],
            },
            {
                "invoiceName": "c2-7",
                "planCode": "c2-7.monthly.postpaid",
                "configurations": [
                    {
                        "name": "region",
                        "values": ["GRA9", "DE1"],  # GRA9 duplicate across flavors
                    }
                ],
            },
        ]

        result = _get_regions_from_catalog()

        # Should merge regions from all pricing variants and deduplicate
        assert len(result) == 4
        assert "GRA9" in result
        assert "BHS5" in result
        assert "SGP1" in result
        assert "DE1" in result
        # Result should be sorted
        assert result == sorted(result)

    @patch("sc_crawler.vendors.ovh._get_catalog")
    @patch("sc_crawler.vendors.ovh._client")
    def test_get_storages_from_catalog(self, mock_client, mock_get_catalog):
        """Test storage extraction from catalog."""
        mock_get_catalog.return_value = {
            "plans": [
                {
                    "planCode": "project",
                    "addonFamilies": [
                        {"name": "storage", "addons": ["storage.consumption"]},
                        {"name": "volume", "addons": ["volume.high-speed.consumption"]},
                    ],
                }
            ],
            "addons": [
                {
                    "planCode": "storage.consumption",
                    "invoiceName": "storage",
                    "configurations": [{"values": ["GRA9"]}],
                    "blobs": {"commercial": {"name": "storage"}},
                },
                {
                    "planCode": "volume.high-speed.consumption",
                    "invoiceName": "volume.high-speed",
                    "configurations": [{"values": ["GRA9"]}],
                    "blobs": {"commercial": {"name": "volume.high-speed"}},
                },
                {
                    "planCode": "no-config-addon",
                    "invoiceName": "no-config",
                    "configurations": [],
                    "blobs": {"commercial": {"name": "no-config"}},
                },
            ],
        }

        result = _get_storages_from_catalog()

        # Should return both storage and volume, but exclude addon without configs
        assert len(result) == 2
        plan_codes = [s["planCode"] for s in result]
        assert "storage.consumption" in plan_codes
        assert "volume.high-speed.consumption" in plan_codes
        assert "no-config-addon" not in plan_codes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
