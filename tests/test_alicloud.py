from unittest.mock import Mock, patch

import pytest

from sc_crawler.inspector import _standardize_gpu_count
from sc_crawler.table_fields import AcceleratorType, Disk, Status, StorageType
from sc_crawler.vendor_helpers import server_status_from_availability_categories
from sc_crawler.vendors._alicloud import (
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_LIFECYCLE,
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_STATUS,
    _DISK_CATEGORY_TO_STORAGE_IDS,
    _accelerator_type,
    _compatible_storage_ids,
    _gpu_manufacturer_of_family,
    _gpu_memory_by_spec,
    _instance_category,
    _local_disk_speed,
    _local_disks,
    _parse_instance_type_disk_categories,
    _warn_unknown_category,
    _warn_unknown_local_disk_speed,
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


def _instance_type_with_disks(type_id, family, disks, gib):
    return {
        "InstanceTypeId": type_id,
        "InstanceTypeFamily": family,
        "LocalStorageAmount": disks,
        "LocalStorageCapacity": gib,
    }


@pytest.mark.parametrize(
    "instance_type,expected",
    [
        # no local disk
        (
            _instance_type_with_disks("ecs.g7.large", "ecs.g7", 0, 0),
            (None, None, None, None),
        ),
        # per instance type table: read IOPS only, GB/s -> MB/s
        (
            _instance_type_with_disks("ecs.i4.large", "ecs.i4", 1, 447),
            (112_500, None, 750, 375),
        ),
        # shared column of two families
        (
            _instance_type_with_disks("ecs.i4r.4xlarge", "ecs.i4r", 1, 894),
            (250_000, None, 1_500, 1_000),
        ),
        (
            _instance_type_with_disks("ecs.i2gne.2xlarge", "ecs.i2gne", 1, 894),
            (250_000, None, 1_500, 1_000),
        ),
        # i2 with more disks: throughput per disk x count, IOPS not published
        (
            _instance_type_with_disks("ecs.i2.8xlarge", "ecs.i2", 4, 1788),
            (None, None, 8_000, 4_000),
        ),
        # i2 largest size: published overall IOPS (not 8 x 300k)
        (
            _instance_type_with_disks("ecs.i2.16xlarge", "ecs.i2", 8, 1788),
            (1_500_000, None, 16_000, 8_000),
        ),
        # i1 formula by capacity, x 2 disks, rounded
        (
            _instance_type_with_disks("ecs.i1.xlarge", "ecs.i1", 2, 104),
            (34_320, 34_320, 291, 177),
        ),
        # i1 caps: same as the published overall speed of the largest size
        (
            _instance_type_with_disks("ecs.i1.14xlarge", "ecs.i1", 2, 1456),
            (480_000, 480_000, 4_000, 2_400),
        ),
        # HDD: single throughput figure per disk, stored as read
        (
            _instance_type_with_disks("ecs.d1.14xlarge", "ecs.d1", 28, 5500),
            (None, None, 5_320, None),
        ),
        (
            _instance_type_with_disks("ecs.d3s.16xlarge", "ecs.d3s", 32, 11100),
            (None, None, 8_320, None),
        ),
        # per disk figure also covers variants of the family
        (
            _instance_type_with_disks("ecs.d1-c14d3.14xlarge", "ecs.d1", 12, 5500),
            (None, None, 2_280, None),
        ),
    ],
)
def test_alicloud_local_disk_speed(instance_type, expected):
    assert _local_disk_speed(instance_type) == expected


@pytest.mark.parametrize(
    "instance_type",
    [
        # same API family as ecs.i2, but other disks and not in the docs
        _instance_type_with_disks("ecs.i2d.21xlarge", "ecs.i2", 4, 3570),
        # same API family as ecs.i5e, but not in the docs
        _instance_type_with_disks("ecs.i5e-grds-4t.2xlarge", "ecs.i5e", 1, 3576),
        # larger than the largest listed size
        _instance_type_with_disks("ecs.d3c.28xlarge", "ecs.d3c", 8, 12800),
        # no figures in the docs at all
        _instance_type_with_disks("ecs.gn5-c4g1.xlarge", "ecs.gn5", 1, 440),
    ],
)
def test_alicloud_local_disk_speed_unknown_is_empty_and_warned_once(instance_type):
    _warn_unknown_local_disk_speed.cache_clear()
    with patch("sc_crawler.vendors._alicloud.logger") as logger:
        assert _local_disk_speed(instance_type) == (None, None, None, None)
        assert _local_disk_speed(instance_type) == (None, None, None, None)
    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert len(warnings) == 1
    assert instance_type["InstanceTypeId"] in warnings[0]


def test_alicloud_inventory_servers_bundled_storage_speed():
    with_disk = {
        **_instance_type("ecs.i4.large", "ecs.i4", "Local SSD"),
        "LocalStorageCategory": "local_ssd_pro",
        "LocalStorageAmount": 1,
        "LocalStorageCapacity": 447,
    }
    # disks with an unknown (empty) category: no disk entries, so no speed
    unknown_category = {
        **_instance_type("ecs.d1.2xlarge", "ecs.d1", "Big Data"),
        "LocalStorageAmount": 4,
        "LocalStorageCapacity": 5500,
    }
    instance_types = [
        with_disk,
        _instance_type("ecs.g7.large", "ecs.g7", "General-purpose"),
        unknown_category,
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
            return_value={},
        ),
    ):
        rows = inventory_servers(Mock(vendor_id="alicloud"))
    speeds = {
        row["server_id"]: (
            row["storage_read_iops_max"],
            row["storage_write_iops_max"],
            row["storage_read_throughput_max"],
            row["storage_write_throughput_max"],
        )
        for row in rows
    }
    assert speeds == {
        "ecs.i4.large": (112_500, None, 750, 375),
        "ecs.g7.large": (None, None, None, None),
        "ecs.d1.2xlarge": (None, None, None, None),
    }
    storages = {row["server_id"]: row["storages"] for row in rows}
    assert storages["ecs.g7.large"] == []
    assert storages["ecs.d1.2xlarge"] == []
    assert storages["ecs.i4.large"] == [
        Disk(
            size=round(447 * 1024**3 / 1000**3),
            storage_type=StorageType.SSD,
            read_iops_max=112_500,
            read_throughput_max=750,
            write_throughput_max=375,
        )
    ]


@pytest.mark.parametrize(
    "amount,speed,expected",
    [
        # docs totals split evenly over the identical disks
        (
            4,
            (1_500_000, None, 16_000, 8_000),
            (375_000, None, 4_000, 2_000),
        ),
        # HDD: read throughput only
        (12, (None, None, 12 * 190, None), (None, None, 190, None)),
        # unknown speed: disks listed without speed
        (2, (None, None, None, None), (None, None, None, None)),
    ],
)
def test_alicloud_local_disks(amount, speed, expected):
    instance_type = {"LocalStorageAmount": amount, "LocalStorageCapacity": 1788}
    disks = _local_disks(instance_type, StorageType.SSD, speed)
    assert len(disks) == amount
    assert {
        (
            d.size,
            d.read_iops_max,
            d.write_iops_max,
            d.read_throughput_max,
            d.write_throughput_max,
        )
        for d in disks
    } == {(round(1788 * 1024**3 / 1000**3), *expected)}


def test_alicloud_local_disks_none():
    speed = (100, 100, 100, 100)
    # no local disk
    assert _local_disks({}, StorageType.SSD, speed) == []
    assert _local_disks({"LocalStorageAmount": 0}, StorageType.SSD, speed) == []
    # unknown category (empty LocalStorageCategory maps to None)
    assert _local_disks({"LocalStorageAmount": 2}, None, speed) == []


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


@pytest.mark.parametrize(
    "gpu_model,gpu_count,expected",
    [
        ("T4", 1, AcceleratorType.GPU),
        (None, 1, AcceleratorType.GPU),
        ("VG1000", 1, AcceleratorType.GPU),
        ("T4", 0, None),
        ("VU9P", 1, AcceleratorType.FPGA),
        ("Arria 10 GX 1150", 1, AcceleratorType.FPGA),
        ("AGF027", 1, AcceleratorType.FPGA),
        ("T408", 12, AcceleratorType.VPU),
        ("ALINPU 800", 4, AcceleratorType.NPU),
        ("PPU 810", 1, AcceleratorType.NPU),
        ("A910E", 8, AcceleratorType.NPU),
        ("A910X", 8, AcceleratorType.NPU),
        ("A910Z", 8, AcceleratorType.NPU),
    ],
)
def test_accelerator_type(gpu_model, gpu_count, expected):
    """GPUSpec models map to their accelerator type, defaulting to GPU."""
    assert _accelerator_type(gpu_model, gpu_count) == expected


@pytest.mark.parametrize(
    "family,expected",
    [
        ("ecs.gn8v", "NVIDIA"),
        ("ecs.ebmgn7t", "NVIDIA"),
        ("ecs.ebmgp7", None),
        ("ecs.av8m", None),
        (None, None),
    ],
)
def test_gpu_manufacturer_of_family(family, expected):
    assert _gpu_manufacturer_of_family(family) == expected
