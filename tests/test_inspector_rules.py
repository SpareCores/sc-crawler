import math
from types import SimpleNamespace

from sc_crawler.inspector_rules import block_reasons


def _server(**overrides):
    """Minimal server stub with defaults that pass every rule."""
    defaults = dict(
        vendor_id="hcloud",
        api_reference="cx22",
        accelerator_count=1,
        memory_amount=8 * 1024,
        vcpus=4,
        storage_size=100,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_block_reasons_accepts_string_or_list():
    server = _server()
    assert block_reasons(server, "membench") == {"membench": []}
    assert block_reasons(server, ["membench", "ffmpeg"]) == {
        "membench": [],
        "ffmpeg": [],
    }


def test_cloud_credit_exhausted():
    for vendor_id in ["alicloud"]:
        reasons = block_reasons(_server(vendor_id=vendor_id), "membench")
        assert reasons["membench"] == ["Cloud credit/budget exhausted."]


def test_cloud_credit_not_applied_outside_big_clouds():
    reasons = block_reasons(_server(vendor_id="hcloud"), "membench")
    assert reasons["membench"] == []


def test_nvidia_tasks_blocked_without_gpus():
    server = _server(accelerator_count=0)
    reasons = block_reasons(server, ["nvidia_smi", "nvbandwidth", "membench"])
    assert reasons["nvidia_smi"] == ["No GPUs available."]
    assert reasons["nvbandwidth"] == ["No GPUs available."]
    assert reasons["membench"] == []


def test_nvidia_tasks_blocked_for_unsupported_skus():
    server = _server(vendor_id="aws", api_reference="g3.4xlarge", accelerator_count=1)
    reasons = block_reasons(server, "nvidia_smi")
    assert reasons["nvidia_smi"] == [
        "Cloud credit/budget exhausted.",
        "GPUs not supported by this server type.",
    ]


def test_nvidia_tasks_allowed_for_supported_gpu_sku():
    server = _server(vendor_id="aws", api_reference="g4dn.xlarge", accelerator_count=1)
    reasons = block_reasons(server, "nvbandwidth")
    assert reasons["nvbandwidth"] == ["Cloud credit/budget exhausted."]


def test_memory_requirements():
    cases = [
        ("membench", 0.9),
        ("compression_text", 1.0),
        ("ffmpeg", 1.0),
        ("llm", 1.0),
        ("vllm", 1.0),
        ("geekbench", 2.1),
        ("pgbench_postgres_ro_durable", 2.0),
    ]
    for task, min_gb in cases:
        min_mib = min_gb * 1024
        below = _server(memory_amount=math.ceil(min_mib) - 1)
        at = _server(memory_amount=math.ceil(min_mib))
        assert block_reasons(below, task)[task] == [
            f"Insufficient memory ({min_gb} GB minimum)."
        ]
        assert block_reasons(at, task)[task] == []


def test_geekbench_and_passmark_blocked_above_32_vcpus():
    server = _server(vcpus=33, memory_amount=8 * 1024)
    reasons = block_reasons(server, ["geekbench", "passmark", "membench"])
    assert reasons["geekbench"] == ["Benchmark doesn't scale beyond 32 cores."]
    assert reasons["passmark"] == ["Benchmark doesn't scale beyond 32 cores."]
    assert reasons["membench"] == []


def test_geekbench_and_passmark_allowed_at_32_vcpus():
    server = _server(vcpus=32, memory_amount=8 * 1024)
    reasons = block_reasons(server, ["geekbench", "passmark"])
    assert reasons == {"geekbench": [], "passmark": []}


def test_storage_blocked_without_bundled_disk():
    server = _server(storage_size=0)
    assert block_reasons(server, "storage")["storage"] == [
        "No bundled storage available."
    ]


def test_storage_allowed_with_bundled_disk():
    server = _server(storage_size=1)
    assert block_reasons(server, "storage")["storage"] == []


def test_stressnglongrun_limited_to_allowlisted_skus():
    allowed = [
        ("aws", "t4g.medium"),
        ("aws", "c7g.large"),
        ("gcp", "e2-medium"),
        ("gcp", "c2d-highcpu-2"),
        ("hcloud", "cx21"),
        ("hcloud", "cx22"),
        ("hcloud", "cax11"),
        ("hcloud", "ccx13"),
    ]
    for vendor_id, api_reference in allowed:
        reasons = block_reasons(
            _server(vendor_id=vendor_id, api_reference=api_reference),
            "stressnglongrun",
        )["stressnglongrun"]
        if vendor_id in ["aws", "gcp"]:
            assert reasons == ["Cloud credit/budget exhausted."]
        else:
            assert reasons == []

    blocked = block_reasons(
        _server(vendor_id="hcloud", api_reference="cx33"), "stressnglongrun"
    )["stressnglongrun"]
    assert blocked == ["Benchmark limited to a few SKUs."]


def test_multiple_reasons_can_stack():
    server = _server(
        vendor_id="aws",
        api_reference="g3.4xlarge",
        accelerator_count=0,
        memory_amount=512,
        vcpus=64,
    )
    reasons = block_reasons(server, ["nvidia_smi", "geekbench"])
    assert reasons["nvidia_smi"] == [
        "Cloud credit/budget exhausted.",
        "No GPUs available.",
        "GPUs not supported by this server type.",
    ]
    assert reasons["geekbench"] == [
        "Cloud credit/budget exhausted.",
        "Insufficient memory (2.1 GB minimum).",
        "Benchmark doesn't scale beyond 32 cores.",
    ]
