import pytest

from sc_crawler.table_fields import AcceleratorType
from sc_crawler.vendors._alicloud import _accelerator_type, _gpu_description


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


@pytest.mark.parametrize(
    "gpu_count,gpu_model,memory_mib,expected",
    [
        (8, "V100", 32768, "8xV100 32 GiB VRAM"),
        (0.5, "A10", 12288, "0.5xA10 12 GiB VRAM"),
        (1, "T4", 1536, "1xT4 1.5 GiB VRAM"),
        (1, None, 16384, None),
        (0, "T4", 0, None),
    ],
)
def test_gpu_description(gpu_count, gpu_model, memory_mib, expected):
    """VRAM is shown in GiB (stored in MiB)."""
    assert _gpu_description(gpu_count, gpu_model, memory_mib) == expected
