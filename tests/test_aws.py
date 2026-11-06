import pytest

from sc_crawler.table_fields import AcceleratorType
from sc_crawler.vendors._aws import (
    _get_gpu_of_instance_type,
    _get_gpus_of_instance_type,
)


def _device(name, manufacturer, count, memory):
    """Build an accelerator device as in the DescribeInstanceTypes response."""
    device = {"Name": name, "Count": count, "MemoryInfo": {"SizeInMiB": memory}}
    if manufacturer:
        device["Manufacturer"] = manufacturer
    return device


@pytest.mark.parametrize(
    "instance_type,expected",
    [
        ({}, (0, 0, 0, None, None, None)),
        ({"FpgaInfo": {"TotalFpgaMemoryInMiB": 0}}, (0, 0, 0, None, None, None)),
        # no memory reported
        (
            {"FpgaInfo": {"Fpgas": [{"Name": "VU9P", "Count": 1}]}},
            (1, 0, 0, "AWS", "VU9P", AcceleratorType.FPGA),
        ),
        (
            {
                "GpuInfo": {
                    "Gpus": [_device("A10G", "NVIDIA", 1, 24576)],
                    "TotalGpuMemoryInMiB": 24576,
                }
            },
            (1, 24576, 24576, "NVIDIA", "A10G", AcceleratorType.GPU),
        ),
        # Habana Gaudi is listed among the GPUs
        (
            {
                "GpuInfo": {
                    "Gpus": [_device("Gaudi HL-205", "Habana", 8, 32768)],
                    "TotalGpuMemoryInMiB": 262144,
                }
            },
            (8, 32768, 262144, "Habana", "Gaudi HL-205", AcceleratorType.NPU),
        ),
        # Inferentia and Trainium have no manufacturer
        (
            {
                "NeuronInfo": {
                    "NeuronDevices": [_device("Inferentia2", None, 12, 32768)],
                    "TotalNeuronDeviceMemoryInMiB": 393216,
                }
            },
            (12, 32768, 393216, "AWS", "Inferentia2", AcceleratorType.NPU),
        ),
        # Trainium2 memory from the AWS docs instead of the API
        (
            {
                "NeuronInfo": {
                    "NeuronDevices": [_device("Trainium2", None, 16, 524288)],
                    "TotalNeuronDeviceMemoryInMiB": 8388608,
                }
            },
            (16, 98304, 1572864, "AWS", "Trainium2", AcceleratorType.NPU),
        ),
        (
            {
                "InferenceAcceleratorInfo": {
                    "Accelerators": [_device("AI 100", "Qualcomm", 8, 16384)],
                    "TotalInferenceMemoryInMiB": 131072,
                }
            },
            (8, 16384, 131072, "Qualcomm", "AI 100", AcceleratorType.NPU),
        ),
        (
            {
                "FpgaInfo": {
                    "Fpgas": [_device("Virtex UltraScale+", "Xilinx", 1, 65536)],
                    "TotalFpgaMemoryInMiB": 65536,
                }
            },
            (1, 65536, 65536, "Xilinx", "Virtex UltraScale+", AcceleratorType.FPGA),
        ),
        (
            {
                "MediaAcceleratorInfo": {
                    "Accelerators": [_device("U30", "Xilinx", 2, 8192)],
                    "TotalMediaMemoryInMiB": 16384,
                }
            },
            (2, 8192, 16384, "Xilinx", "U30", AcceleratorType.VPU),
        ),
    ],
)
def test_accelerators_of_instance_type(instance_type, expected):
    """Accelerator summary and type for each AWS accelerator info field."""
    assert _get_gpu_of_instance_type(instance_type) == expected


def test_accelerators_expanded_by_count():
    """Devices are expanded into individual accelerators by their count."""
    instance_type = {
        "NeuronInfo": {
            "NeuronDevices": [_device("Trainium", None, 16, 32768)],
            "TotalNeuronDeviceMemoryInMiB": 524288,
        }
    }
    accelerators = _get_gpus_of_instance_type(instance_type)
    assert len(accelerators) == 16
    assert accelerators[0].manufacturer == "AWS"
    assert accelerators[0].model == "Trainium"
    assert accelerators[0].memory == 32768
