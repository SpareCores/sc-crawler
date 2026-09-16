import pytest

from sc_crawler.inspector import _standardize_gpu_count


def test_standardize_gpu_count_from_alicloud_gpuspec():
    """AliCloud encodes fractional vGPUs in GPUSpec, e.g. "NVIDIA P4*1/4"."""
    assert _standardize_gpu_count("NVIDIA P4*1/4", 1) == 0.25
    assert _standardize_gpu_count("NVIDIA T4/8", 1) == 0.125
    assert _standardize_gpu_count("NVIDIA A10*1", 1) == 1
    # whole counts are returned as-is, so descriptions stay "8xV100"
    assert _standardize_gpu_count("NVIDIA V100", 8) == 8
    assert isinstance(_standardize_gpu_count("NVIDIA V100", 8), int)
    assert _standardize_gpu_count("", 0) == 0


def test_standardize_gpu_count_from_aws_gpu_memory():
    """AWS g6f / gr6f report no GPU count, only the L4 slice memory."""
    assert _standardize_gpu_count("L4", 0, 5722) == pytest.approx(0.25)
    assert _standardize_gpu_count("L4", 0, 22888) == pytest.approx(1)
    # other models without a count stay untouched
    assert _standardize_gpu_count("A100", 0, 40960) == 0


def test_standardize_gpu_count_from_gcp_description():
    """GCP machineTypes report count=1 for G4 vGPU slices, fraction is in description."""
    assert (
        _standardize_gpu_count(
            gpu_count=1,
            description="Graphics Optimized: 1/8 NVIDIA RTX PRO 6000 GPU, 6 vCPUs, 22GB RAM",
        )
        == 0.125
    )
    assert (
        _standardize_gpu_count(
            gpu_count=4,
            description="Accelerator Optimized: 4 NVIDIA GB300 GPU, 144 vCPUs, 960GB RAM",
        )
        == 4
    )
    # TPU machines and vendor descriptions without GPUs keep the API count
    assert (
        _standardize_gpu_count(
            gpu_count=1, description="24 vCPUs, 48 GB RAM, 1 Google TPUs"
        )
        == 1
    )
    assert _standardize_gpu_count(gpu_count=2, description="g2 family (8 vCPUs)") == 2
