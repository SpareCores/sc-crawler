import json
from datetime import datetime, timezone

from sc_crawler.inspector import _pgbench_benchmark_scores, inspect_server_benchmarks
from sc_crawler.lookup import (
    _BENCHMARK_FAMILY_INDEPENDENT_NOTE,
    _BENCHMARK_LLM_SPEED_NOTE,
    _BENCHMARK_SINGLE_SESSION_NOTE,
    _BENCHMARK_SINGLE_THREAD_NOTE,
    benchmarks,
)
from sc_crawler.table_bases import ServerBase
from sc_crawler.table_fields import Status


def _bench(benchmark_id: str):
    return next(b for b in benchmarks if b.benchmark_id == benchmark_id)


def test_geekbench_scaling_notes():
    assert "32 vCPUs" in _bench("geekbench:html5_browser").note
    assert "4 vCPUs" in _bench("geekbench:text_processing").note
    assert "64 vCPUs" in _bench("geekbench:score").note
    assert _bench("geekbench:clang").note is None


def test_passmark_scaling_notes():
    assert "16 vCPUs" in _bench("passmark:memory_mark").note
    assert _bench("passmark:memory_latency").note == _BENCHMARK_FAMILY_INDEPENDENT_NOTE
    assert _bench("passmark:cpu_single_threaded_test").note == (
        _BENCHMARK_SINGLE_THREAD_NOTE
    )
    assert _bench("passmark:cpu_compression_test").note is None


def test_stress_ng_and_bogomips_notes():
    assert _bench("stress_ng:best1").note == _BENCHMARK_SINGLE_THREAD_NOTE
    assert _bench("stress_ng:bestn").note is None
    assert "pseudo-benchmark" in _bench("bogomips").note


def test_throughput_latency_notes():
    redis_latency = _bench("redis:latency").note
    assert "redis:rps" in redis_latency
    assert "standalone benchmark" in redis_latency
    assert "filter" in redis_latency

    static_latency = _bench("static_web:latency").note
    assert "static_web:rps" in static_latency
    assert "filter" in static_latency
    assert "listener bottleneck" not in static_latency

    static_rps = _bench("static_web:rps").note
    assert static_rps is not None
    assert "listener bottleneck" in static_rps


def test_llm_speed_notes():
    text_gen = _bench("llm_speed:text_generation")
    prompt = _bench("llm_speed:prompt_processing")
    assert text_gen.note == _BENCHMARK_LLM_SPEED_NOTE
    assert prompt.note == _BENCHMARK_LLM_SPEED_NOTE
    assert "llama.cpp" in text_gen.note
    assert "vLLM benchmarks" in text_gen.note


def test_pgbench_notes_and_config_fields():
    raw = _bench("pgbench:heavy_read_only")
    single = _bench("pgbench:heavy_read_only:single")
    peak = _bench("pgbench:heavy_read_only:peak")

    assert "integer" in raw.config_fields["concurrency"].lower()
    assert raw.note is None
    assert single.note == _BENCHMARK_SINGLE_SESSION_NOTE
    assert single.note != _BENCHMARK_SINGLE_THREAD_NOTE
    assert peak.note is None
    assert not single.config_fields
    assert not peak.config_fields


def _sample_pgbench_json():
    return {
        "score": 12000.0,
        "latency_avg_ms": 8.5,
        "peak_concurrency": 8,
        "postgres": {"server_version": "16.3 (Debian 16.3-1)"},
        "sizes": [
            {
                "profile": [
                    {"concurrency": 1, "score": 3000.0, "latency_avg_ms": 2.1},
                    {"concurrency": 4, "score": 9000.0, "latency_avg_ms": 4.2},
                    {"concurrency": 8, "score": 12000.0, "latency_avg_ms": 8.5},
                    {"concurrency": 16, "score": 11000.0, "latency_avg_ms": 12.0},
                ]
            }
        ],
    }


def test_pgbench_benchmark_scores_raw_single_and_peak(tmp_path, monkeypatch):
    stdout = tmp_path / "stdout"
    stdout.write_text(json.dumps(_sample_pgbench_json()))

    monkeypatch.setattr(
        "sc_crawler.inspector._server_framework_stdout_path",
        lambda server, framework: stdout,
    )
    monkeypatch.setattr(
        "sc_crawler.inspector._server_framework_meta",
        lambda server, framework: {
            "end": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "version": "16.3",
            "kernel_version": "6.8.0",
        },
    )

    server = ServerBase(
        vendor_id="aws",
        server_id="m5.large",
        name="m5.large",
        api_reference="m5.large",
        display_name="m5.large",
        description="test",
        vcpus=8,
        memory_amount=8192,
        storage_size=0,
        status=Status.ACTIVE,
    )

    scores = _pgbench_benchmark_scores(server)
    by_id = {}
    for score in scores:
        by_id.setdefault(score["benchmark_id"], []).append(score)

    raw = by_id["pgbench:heavy_read_only"]
    assert len(raw) == 4
    assert [r["config"]["concurrency"] for r in raw] == [1, 4, 8, 16]
    assert all(isinstance(r["config"]["concurrency"], int) for r in raw)
    assert [r["score"] for r in raw] == [3000.0, 9000.0, 12000.0, 11000.0]
    assert raw[0]["note"] == "Latency: 2.1 ms."
    assert [r["environment"]["latency_avg_ms"] for r in raw] == [2.1, 4.2, 8.5, 12.0]
    assert all(r["environment"]["database_engine_version"] == "16.3" for r in raw)
    assert all(r["environment"]["kernel_version"] == "6.8.0" for r in raw)
    # Prove each row got its own environment dict (no shared-aliasing).
    raw[0]["environment"]["latency_avg_ms"] = 999.0
    assert raw[1]["environment"]["latency_avg_ms"] == 4.2

    single = by_id["pgbench:heavy_read_only:single"]
    assert len(single) == 1
    assert "config" not in single[0]
    assert single[0]["score"] == 3000.0
    assert single[0]["note"] == "Latency: 2.1 ms."
    assert single[0]["environment"]["latency_avg_ms"] == 2.1
    assert single[0]["environment"]["database_engine_version"] == "16.3"

    peak = by_id["pgbench:heavy_read_only:peak"]
    assert len(peak) == 1
    assert "config" not in peak[0]
    assert peak[0]["score"] == 12000.0
    assert peak[0]["note"] == "Latency: 8.5 ms, concurrency: 8."
    assert peak[0]["environment"]["latency_avg_ms"] == 8.5
    assert peak[0]["environment"]["peak_concurrency"] == 8
    assert peak[0]["environment"]["database_engine_version"] == "16.3"


def _nvbandwidth_testcase(name, status="Passed", matrix=None, total=None):
    testcase = {"name": name, "status": status}
    if matrix is not None:
        testcase["bandwidth_matrix"] = matrix
        testcase["sum"] = total
    return testcase


def _nvbandwidth_payload(testcases, driver="535.183.01", cuda=12060, version="v0.5"):
    return {
        "nvbandwidth": {
            "Driver Version": driver,
            "CUDA Runtime Version": cuda,
            "version": version,
            "testcases": testcases,
        }
    }


def _nvbandwidth_scores(tmp_path, monkeypatch, payload):
    stdout = tmp_path / "stdout"
    stdout.write_text(json.dumps(payload))
    monkeypatch.setattr(
        "sc_crawler.inspector._server_framework_path",
        lambda server, framework, relpath=None: stdout,
    )
    monkeypatch.setattr(
        "sc_crawler.inspector._server_framework_meta",
        lambda server, framework: {
            "end": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "version": "v0.5",
            "kernel_version": "6.8.0",
        },
    )
    server = ServerBase(
        vendor_id="ovh",
        server_id="t1-45",
        name="t1-45",
        api_reference="t1-45",
        display_name="t1-45",
        description="test",
        vcpus=1,
        memory_amount=1024,
        storage_size=0,
        status=Status.ACTIVE,
    )
    scores = inspect_server_benchmarks(server)
    return {
        score["benchmark_id"]: score
        for score in scores
        if score["benchmark_id"].startswith("nvbandwidth:")
    }


def test_nvbandwidth_single_gpu_skips_waived_p2p(tmp_path, monkeypatch):
    scores = _nvbandwidth_scores(
        tmp_path,
        monkeypatch,
        _nvbandwidth_payload(
            [
                _nvbandwidth_testcase(
                    "host_to_all_memcpy_ce", matrix=[["12.1423"]], total=12.14228004
                ),
                _nvbandwidth_testcase(
                    "all_to_host_memcpy_ce", matrix=[["12.9626"]], total=12.962573629
                ),
                _nvbandwidth_testcase(
                    "host_to_all_bidirectional_memcpy_ce",
                    matrix=[["11.319"]],
                    total=11.318987834,
                ),
                _nvbandwidth_testcase(
                    "all_to_host_bidirectional_memcpy_ce",
                    matrix=[["11.3216"]],
                    total=11.321613496,
                ),
                _nvbandwidth_testcase(
                    "host_to_device_memcpy_ce", matrix=[["10.4311"]], total=10.431058064
                ),
                _nvbandwidth_testcase(
                    "device_to_host_memcpy_ce", matrix=[["12.966"]], total=12.966017292
                ),
                _nvbandwidth_testcase(
                    "host_device_latency_sm",
                    matrix=[["821.923"]],
                    total=821.9230480072464,
                ),
                _nvbandwidth_testcase(
                    "host_to_device_memcpy_sm", matrix=[["10.5466"]], total=10.546557803
                ),
                _nvbandwidth_testcase(
                    "device_to_device_memcpy_write_ce", status="Waived"
                ),
                _nvbandwidth_testcase(
                    "device_to_device_bidirectional_memcpy_write_ce", status="Waived"
                ),
                _nvbandwidth_testcase("device_to_device_latency_sm", status="Waived"),
                _nvbandwidth_testcase("all_to_one_write_ce", status="Waived"),
            ]
        ),
    )
    assert scores["nvbandwidth:all:host_to_gpu"]["score"] == 12.14228004
    assert scores["nvbandwidth:all:gpu_to_host"]["score"] == 12.962573629
    assert scores["nvbandwidth:all:duplex"]["score"] == 11.318987834
    assert scores["nvbandwidth:slot:host_to_gpu"]["score"] == 10.431058064
    assert scores["nvbandwidth:slot:latency"]["score"] == 821.9230480072464
    assert scores["nvbandwidth:efficiency:sm_ce_ratio"]["score"] == 1.0
    assert "nvbandwidth:p2p:single" not in scores
    environment = scores["nvbandwidth:all:host_to_gpu"]["environment"]
    assert environment["driver_version"] == "535.183.01"
    assert environment["cuda_runtime_version"] == 12060
    assert environment["nvbandwidth_version"] == "v0.5"
    assert environment["gpu_count"] == 1
    assert environment["p2p_supported"] is False
    assert environment["kernel_version"] == "6.8.0"


def test_nvbandwidth_multi_gpu_averages_cells(tmp_path, monkeypatch):
    scores = _nvbandwidth_scores(
        tmp_path,
        monkeypatch,
        _nvbandwidth_payload(
            [
                _nvbandwidth_testcase(
                    "host_to_device_memcpy_ce",
                    matrix=[["26.6868", "26.6888"]],
                    total=53.375511724,
                ),
                _nvbandwidth_testcase(
                    "host_to_device_memcpy_sm",
                    matrix=[["20.0", "20.0"]],
                    total=40.0,
                ),
                _nvbandwidth_testcase(
                    "device_to_device_memcpy_write_ce",
                    matrix=[["N/A", "277.166"], ["277.453", "N/A"]],
                    total=554.618858717,
                ),
                _nvbandwidth_testcase(
                    "all_to_one_write_ce",
                    matrix=[["277.433", "277.204"]],
                    total=554.6371479825768,
                ),
            ]
        ),
    )
    assert scores["nvbandwidth:slot:host_to_gpu"]["score"] == 53.375511724 / 2
    assert scores["nvbandwidth:p2p:single"]["score"] == 554.618858717 / 2
    assert scores["nvbandwidth:p2p:gather"]["score"] == 554.6371479825768 / 2
    assert scores["nvbandwidth:efficiency:sm_ce_ratio"]["score"] == 40.0 / 53.375511724
    assert "nvbandwidth:p2p:duplex" not in scores
    environment = scores["nvbandwidth:p2p:single"]["environment"]
    assert environment["gpu_count"] == 2
    assert environment["p2p_supported"] is True
