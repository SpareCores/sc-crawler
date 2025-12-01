"""Unit tests for OVHcloud vendor module."""

from unittest.mock import Mock, patch

import pytest

from sc_crawler.vendors.ovh import (
    HOURS_PER_MONTH,
    MIB_PER_GIB,
    MICROCENTS_PER_CURRENCY_UNIT,
    _get_gpu_info,
    _get_server_family,
    inventory_compliance_frameworks,
)


class TestConstants:
    """Test module-level constants."""

    def test_constants_values(self):
        """Test that constants have expected values."""
        assert HOURS_PER_MONTH == 730
        assert MICROCENTS_PER_CURRENCY_UNIT == 100_000_000
        assert MIB_PER_GIB == 1024


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
