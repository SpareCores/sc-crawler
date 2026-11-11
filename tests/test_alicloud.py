from unittest.mock import Mock, patch

from sc_crawler.inspector import _standardize_gpu_count
from sc_crawler.table_fields import Status
from sc_crawler.vendor_helpers import server_status_from_availability_categories
from sc_crawler.vendors._alicloud import (
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_LIFECYCLE,
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_STATUS,
    _DISK_CATEGORY_TO_STORAGE_IDS,
    _compatible_storage_ids,
    _gpu_memory_by_spec,
    _instance_category,
    _parse_instance_type_disk_categories,
    _warn_unknown_category,
    inventory_servers,
    inventory_storages,
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
            == "General Purpose"
        )
        # spelling unified with the other vendors: no hyphens
        assert (
            _instance_category(
                _instance_type("ecs.c7.large", "ecs.c7", "Compute-optimized")
            )
            == "Compute Optimized"
        )
        assert (
            _instance_category(
                _instance_type("ecs.hfc6.large", "ecs.hfc6", "High Performance Compute")
            )
            == "High Performance Computing"
        )
        # retired family without category in the API: category of the docs
        assert (
            _instance_category(_instance_type("ecs.n1.small", "ecs.n1", "")) == "Shared"
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
        patch(
            "sc_crawler.vendors._alicloud._get_instance_type_disk_categories",
            return_value={"ecs.g7.large": ["cloud_essd", "cloud_ssd"]},
        ),
    ):
        vendor = Mock(vendor_id="alicloud")
        rows = inventory_servers(vendor)
    by_id = {row["server_id"]: row for row in rows}
    assert by_id["ecs.g7.large"]["compatible_storage_ids"] == [
        "cloud_essd-pl0",
        "cloud_essd-pl1",
        "cloud_essd-pl2",
        "cloud_essd-pl3",
        "cloud_ssd",
    ]
    # no disk data for this instance type: unknown (None) and one summary warning
    assert by_id["ecs.gn5-c4g1.xlarge"]["compatible_storage_ids"] is None
    vendor.log.assert_called_once()
    assert "1 instance types" in vendor.log.call_args.args[0]
    assert by_id["ecs.g7.large"]["family"] == "General Purpose"
    assert by_id["ecs.g7.large"]["series"] == "ecs.g7"
    assert by_id["ecs.gn5-c4g1.xlarge"]["family"] == "Compute Optimized with GPU"
    assert by_id["ecs.gn5-c4g1.xlarge"]["series"] == "ecs.gn5"
    # description still shows the series
    assert by_id["ecs.g7.large"]["description"].startswith("ecs.g7 family (")


def test_alicloud_parse_instance_type_disk_categories_merges_zones():
    zones = [
        {
            "AvailableResources": {
                "ResourcesInfo": [
                    {
                        "DataDiskCategories": {
                            "supportedDataDiskCategory": ["cloud_essd"]
                        },
                        "InstanceTypes": {
                            "supportedInstanceType": ["ecs.g7.large", "ecs.c7.large"]
                        },
                    }
                ]
            }
        },
        {
            "AvailableResources": {
                "ResourcesInfo": [
                    {
                        "DataDiskCategories": {
                            "supportedDataDiskCategory": ["cloud_ssd", "cloud_essd"]
                        },
                        "InstanceTypes": {"supportedInstanceType": ["ecs.g7.large"]},
                    }
                ]
            }
        },
        {},
    ]
    assert _parse_instance_type_disk_categories(zones) == {
        "ecs.g7.large": ["cloud_essd", "cloud_ssd"],
        "ecs.c7.large": ["cloud_essd"],
    }


def test_alicloud_compatible_storage_ids():
    assert _compatible_storage_ids(["cloud_efficiency", "ephemeral_ssd"]) == [
        "cloud_efficiency"
    ]
    assert _compatible_storage_ids(["ephemeral_ssd"]) == []
    assert _compatible_storage_ids([]) == []


def test_alicloud_disk_category_mapping_matches_storage_ids():
    storage_ids = {s["storage_id"] for s in inventory_storages(Mock(vendor_id="a"))}
    mapped = {i for ids in _DISK_CATEGORY_TO_STORAGE_IDS.values() for i in ids}
    assert mapped == storage_ids


def test_alicloud_gpu_memory_by_spec_only_when_unambiguous():
    instance_types = [
        {"InstanceTypeId": "ecs.gn7s-c8g1.2xlarge", "GPUSpec": "NVIDIA A30"},
        {"InstanceTypeId": "x", "GPUSpec": "NVIDIA A30", "GPUMemorySize": 24},
        {"InstanceTypeId": "y", "GPUSpec": "NVIDIA V100", "GPUMemorySize": 16},
        {"InstanceTypeId": "z", "GPUSpec": "NVIDIA V100", "GPUMemorySize": 32.0},
        {"InstanceTypeId": "ecs.gn4.8xlarge", "GPUSpec": "NVIDIA M40"},
        {"InstanceTypeId": "ecs.g7nex.large", "GPUSpec": ""},
    ]
    assert _gpu_memory_by_spec(instance_types) == {"NVIDIA A30": 24.0}


def test_alicloud_server_lifecycle_keeps_out_of_stock_types_active():
    lifecycle = _ALICLOUD_STATUS_CATEGORY_TO_SERVER_LIFECYCLE
    assert (
        server_status_from_availability_categories({"WithoutStock"}, lifecycle)
        == Status.ACTIVE
    )
    assert (
        server_status_from_availability_categories({"ClosedWithoutStock"}, lifecycle)
        == Status.RETIRED
    )
    assert server_status_from_availability_categories(set(), lifecycle) == (
        Status.INACTIVE
    )
    # per-zone prices still follow the stock
    assert not _ALICLOUD_STATUS_CATEGORY_TO_SERVER_STATUS["WithoutStock"].is_orderable
