import pytest

from sc_crawler.table_fields import AcceleratorType, Status
from sc_crawler.vendor_helpers import server_status_from_availability_categories
from sc_crawler.vendors._alicloud import (
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_LIFECYCLE,
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_STATUS,
    _accelerator_type,
    _gpu_memory_by_spec,
)


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
        ("Xilinx VU9p", 1, AcceleratorType.FPGA),
        ("INTEL ARRIA 10 GX 1150", 1, AcceleratorType.FPGA),
        ("AGF 027", 1, AcceleratorType.FPGA),
        ("NETINT T408", 12, AcceleratorType.VPU),
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
