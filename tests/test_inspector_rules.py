import math
from types import SimpleNamespace

from sc_crawler.inspector_rules import block_reasons
from sc_crawler.table_bases import DatabaseBase
from sc_crawler.table_fields import DatabaseHaLevel, DatabaseHaStrategy, Status

_SINGLE_NODE_BLOCK = "Database doesn't support single-node deployment."


def _server(**overrides):
    """Minimal server stub with defaults that pass every rule."""
    defaults = dict(
        vendor_id="hcloud",
        api_reference="cx22",
        gpu_count=1,
        memory_amount=8 * 1024,
        vcpus=4,
        storage_size=100,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _database(**overrides):
    """Minimal DatabaseBase that supports single-node deployment by default."""
    defaults = dict(
        vendor_id="hcloud",
        database_id="db-dedicated-2",
        name="db-dedicated-2",
        api_reference="db-dedicated-2",
        display_name="db-dedicated-2",
        description="test database",
        status=Status.ACTIVE,
        ha=[DatabaseHaLevel.NONE],
        ha_strategy=[DatabaseHaStrategy.NONE],
    )
    defaults.update(overrides)
    return DatabaseBase(**defaults)


def test_block_reasons_accepts_string_or_list():
    server = _server()
    assert block_reasons(server, "membench") == {"membench": []}
    assert block_reasons(server, ["membench", "ffmpeg"]) == {
        "membench": [],
        "ffmpeg": [],
    }


def test_database_allows_tasks_when_single_node_supported():
    database = _database(
        ha=[DatabaseHaLevel.MULTI_ZONE, DatabaseHaLevel.NONE],
        ha_strategy=[DatabaseHaStrategy.PASSIVE_STANDBY, DatabaseHaStrategy.NONE],
    )
    assert block_reasons(database, "membench") == {"membench": []}
    assert block_reasons(database, ["nvidia_smi", "membench", "storage"]) == {
        "nvidia_smi": [],
        "membench": [],
        "storage": [],
    }


def test_database_blocked_without_ha_none():
    database = _database(ha=[DatabaseHaLevel.MULTI_ZONE])
    assert block_reasons(database, "membench")["membench"] == [_SINGLE_NODE_BLOCK]


def test_database_blocked_without_ha_strategy_none():
    database = _database(ha_strategy=[DatabaseHaStrategy.PASSIVE_STANDBY])
    assert block_reasons(database, "membench")["membench"] == [_SINGLE_NODE_BLOCK]


def test_database_blocked_without_either_none():
    database = _database(
        ha=[DatabaseHaLevel.SINGLE_ZONE],
        ha_strategy=[DatabaseHaStrategy.READABLE_CLUSTER],
    )
    reasons = block_reasons(database, ["membench", "storage"])
    assert reasons == {
        "membench": [_SINGLE_NODE_BLOCK],
        "storage": [_SINGLE_NODE_BLOCK],
    }


def test_database_vendor_and_single_node_reasons_stack():
    database = _database(
        vendor_id="aws",
        ha=[DatabaseHaLevel.MULTI_ZONE],
    )
    assert block_reasons(database, "membench")["membench"] == [
        "Cloud credit/budget exhausted.",
        _SINGLE_NODE_BLOCK,
    ]


def test_database_skips_server_only_rules():
    # Would fail mem/storage/GPU server rules if those ran; Database continues early
    database = _database(memory_amount=1, storage_size=0, vcpus=64)
    assert block_reasons(database, ["membench", "storage", "geekbench"]) == {
        "membench": [],
        "storage": [],
        "geekbench": [],
    }


def test_cloud_credit_exhausted():
    for vendor_id in ["alicloud"]:
        reasons = block_reasons(_server(vendor_id=vendor_id), "membench")
        assert reasons["membench"] == ["Cloud credit/budget exhausted."]


def test_cloud_credit_not_applied_outside_big_clouds():
    reasons = block_reasons(_server(vendor_id="hcloud"), "membench")
    assert reasons["membench"] == []


def test_nvidia_tasks_blocked_without_gpus():
    server = _server(gpu_count=0)
    reasons = block_reasons(server, ["nvidia_smi", "nvbandwidth", "membench"])
    assert reasons["nvidia_smi"] == ["No GPUs available."]
    assert reasons["nvbandwidth"] == ["No GPUs available."]
    assert reasons["membench"] == []


def test_nvidia_tasks_blocked_for_unsupported_skus():
    server = _server(vendor_id="aws", api_reference="g3.4xlarge", gpu_count=1)
    reasons = block_reasons(server, "nvidia_smi")
    assert reasons["nvidia_smi"] == [
        "Cloud credit/budget exhausted.",
        "GPUs not supported by this server type.",
    ]


def test_nvidia_tasks_allowed_for_supported_gpu_sku():
    server = _server(vendor_id="aws", api_reference="g4dn.xlarge", gpu_count=1)
    reasons = block_reasons(server, "nvbandwidth")
    assert reasons["nvbandwidth"] == ["Cloud credit/budget exhausted."]


def test_memory_requirements():
    cases = [
        ("membench", 0.9),
        ("compression_text", 1.0),
        ("ffmpeg", 1.0),
        ("llm", 1.0),
        ("vllm", 2.0),
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
        gpu_count=0,
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
