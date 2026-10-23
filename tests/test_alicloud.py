from unittest.mock import Mock, patch

from sc_crawler.inspector import _standardize_gpu_count
from sc_crawler.vendors._alicloud import (
    _instance_category,
    _warn_unknown_category,
    inventory_servers,
)


def test_standardize_gpu_count_from_alicloud_gpuspec():
    """AliCloud encodes fractional vGPUs in GPUSpec, e.g. "NVIDIA P4*1/4"."""
    assert _standardize_gpu_count("NVIDIA P4*1/4", 1) == 0.25
    assert _standardize_gpu_count("NVIDIA T4/8", 1) == 0.125
    assert _standardize_gpu_count("NVIDIA A10*1", 1) == 1
    # whole counts are returned as-is, so descriptions stay "8xV100"
    assert _standardize_gpu_count("NVIDIA V100", 8) == 8
    assert isinstance(_standardize_gpu_count("NVIDIA V100", 8), int)
    assert _standardize_gpu_count("", 0) == 0


def _instance_type(type_id, family, category):
    return {
        "InstanceTypeId": type_id,
        "InstanceTypeFamily": family,
        "InstanceCategory": category,
        "CpuArchitecture": "X86",
        "CpuCoreCount": 2,
        "MemorySize": 8.0,
        "LocalStorageCategory": "",
        "GPUSpec": "",
        "GPUAmount": 0,
        "PhysicalProcessorModel": "",
        "InstanceFamilyLevel": "EnterpriseLevel",
    }


def test_alicloud_instance_category_is_family_and_warned_once():
    _warn_unknown_category.cache_clear()
    with patch("sc_crawler.vendors._alicloud.logger") as logger:
        assert (
            _instance_category(
                _instance_type("ecs.g7.large", "ecs.g7", "General-purpose")
            )
            == "General-purpose"
        )
        missing = _instance_type("ecs.new.large", "ecs.new", "")
        assert _instance_category(missing) is None
        assert _instance_category(missing) is None
    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert len(warnings) == 1
    assert "ecs.new.large" in warnings[0]


def test_alicloud_inventory_servers_sets_family_and_series():
    instance_types = [
        _instance_type("ecs.g7.large", "ecs.g7", "General-purpose"),
        _instance_type("ecs.gn5-c4g1.xlarge", "ecs.gn5", "Compute-optimized with GPU"),
    ]
    with (
        patch(
            "sc_crawler.vendors._alicloud._get_instance_types",
            return_value=instance_types,
        ),
        patch(
            "sc_crawler.vendors._alicloud._get_region_availability_info",
            return_value={},
        ),
    ):
        rows = inventory_servers(Mock(vendor_id="alicloud"))
    by_id = {row["server_id"]: row for row in rows}
    assert by_id["ecs.g7.large"]["family"] == "General-purpose"
    assert by_id["ecs.g7.large"]["series"] == "ecs.g7"
    assert by_id["ecs.gn5-c4g1.xlarge"]["family"] == "Compute-optimized with GPU"
    assert by_id["ecs.gn5-c4g1.xlarge"]["series"] == "ecs.gn5"
    # description still shows the series
    assert by_id["ecs.g7.large"]["description"].startswith("ecs.g7 family (")
