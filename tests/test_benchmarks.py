import json
from datetime import datetime, timezone

import pytest

from sc_crawler.inspector import (
    _duration,
    _measured_at,
    _pgbench_benchmark_scores,
    inspect_server_benchmarks,
)
from sc_crawler.lookup import (
    _BENCHMARK_FAMILY_INDEPENDENT_NOTE,
    _BENCHMARK_LLM_SPEED_NOTE,
    _BENCHMARK_SINGLE_SESSION_NOTE,
    _BENCHMARK_SINGLE_THREAD_NOTE,
    _STRESS_NG_METHODS,
    benchmarks,
    stress_ng_benchmark_id,
)
from sc_crawler.table_bases import ServerBase
from sc_crawler.table_fields import Parallelism, Status


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


def test_stress_ng_method_catalog():
    assert len(_STRESS_NG_METHODS) == 84
    assert len({method for method, _, _ in _STRESS_NG_METHODS}) == 84
    ids = [benchmark.benchmark_id for benchmark in benchmarks]
    assert len(ids) == len(set(ids))

    memcpy = _bench("stress_ng:memcpy")
    assert memcpy.name == "stress-ng memcpy"
    assert memcpy.category == "stress-ng"
    assert memcpy.subcategory == "Memory"
    assert memcpy.framework == "stress_ng"
    assert memcpy.unit == "Bogo operations per second (ops/s)"
    assert memcpy.config_fields["cores"] == "Single-Core or Multi-Core stress tests."
    assert memcpy.description.startswith(
        "Start N workers that copies data to and from a buffer using memcpy "
        "and then move the data in the buffer with memmove with 3 different "
        "alignments."
    )
    assert "bogo operations per second" in memcpy.description
    assert _bench("stress_ng:bitonicsort").description.startswith(
        "Start N workers that sort 32 bit integers using bitonic sort."
    )
    assert _bench("stress_ng:bitonicsort").subcategory == "Algorithms"
    assert _bench("stress_ng:matrix_3d").name == "stress-ng matrix-3d"
    assert _bench("stress_ng:tlb_shootdown").subcategory == "Hypervisor"
    assert stress_ng_benchmark_id("matrix-3d") == "stress_ng:matrix_3d"
    assert stress_ng_benchmark_id("not-a-stressor") is None
    # overlaps stress_ng:cpu_all
    assert stress_ng_benchmark_id("cpu") is None
    assert "Operations used are:" not in _bench("stress_ng:fma").description
    assert "goodness-of-fit" in _bench("stress_ng:hash").description
    assert "0..499999" in _bench("stress_ng:hrtimers").description
    assert {subcategory for _, subcategory, _ in _STRESS_NG_METHODS} == {
        "CPU integer",
        "CPU float/SIMD",
        "Cryptography",
        "Compression",
        "Memory",
        "Algorithms",
        "Hypervisor",
    }


def _stressng_scores(tmp_path, monkeypatch, payload):
    stdout = tmp_path / "stdout"
    stdout.write_text(json.dumps(payload))
    monkeypatch.setattr(
        "sc_crawler.inspector._server_framework_stdout_path",
        lambda server, framework: stdout,
    )
    monkeypatch.setattr(
        "sc_crawler.inspector._server_framework_meta",
        lambda server, framework: {
            "end": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "version": "0.18.12",
            "kernel_version": "6.8.0",
        },
    )
    server = ServerBase(
        vendor_id="aws",
        server_id="c8i.96xlarge",
        name="c8i.96xlarge",
        api_reference="c8i.96xlarge",
        display_name="c8i.96xlarge",
        description="test",
        vcpus=384,
        memory_amount=786432,
        storage_size=0,
        status=Status.ACTIVE,
    )
    by_id = {}
    for score in inspect_server_benchmarks(server):
        if score["benchmark_id"].startswith("stress_ng:") and score[
            "benchmark_id"
        ] not in {
            "stress_ng:cpu_all",
            "stress_ng:div16",
            "stress_ng:best1",
            "stress_ng:bestn",
        }:
            by_id.setdefault(score["benchmark_id"], []).append(score)
    return by_id


def test_stressng_benchmark_scores(tmp_path, monkeypatch):
    by_id = _stressng_scores(
        tmp_path,
        monkeypatch,
        {
            "stressors": {
                "memcpy": {
                    "1": {"bogo_ops_per_sec": 761.69},
                    "384": {"bogo_ops_per_sec": 148114.96},
                },
                "matrix-3d": {"1": {"bogo_ops_per_sec": 610.84}},
                "ipsec-mb": {"1": None, "384": None},
                "vm": {"1": {"bogo_ops_per_sec": 142417.37}, "384": None},
                "cache": {
                    "1": {"bogo_ops_per_sec": 251720.14},
                    "384": {"bogo_ops_per_sec": 0.0},
                },
                "not-a-method": {"1": {"bogo_ops_per_sec": 1.0}},
                # bad entry must not stop later stressors
                "atomic": {"1": {"bogo_ops_per_sec": None}},
                "branch": {"1": {"bogo_ops_per_sec": 42.0}},
            }
        },
    )

    assert set(by_id) == {
        "stress_ng:branch",
        "stress_ng:cache",
        "stress_ng:matrix_3d",
        "stress_ng:memcpy",
        "stress_ng:vm",
    }
    memcpy = by_id["stress_ng:memcpy"]
    assert [row["config"]["cores"] for row in memcpy] == [
        Parallelism.SINGLE,
        Parallelism.MULTI,
    ]
    assert [row["score"] for row in memcpy] == [761.69, 148114.96]
    assert memcpy[0]["framework_version"] == "0.18.12"
    assert memcpy[0]["environment"]["kernel_version"] == "6.8.0"
    assert memcpy[0]["environment"]["measured_at"] == "2026-01-01T00:00:00+00:00"
    assert by_id["stress_ng:matrix_3d"][0]["config"]["cores"] == Parallelism.SINGLE
    assert [row["config"]["cores"] for row in by_id["stress_ng:vm"]] == [
        Parallelism.SINGLE
    ]
    # zero bogo_ops_per_sec is skipped (timeout / no completed ops)
    assert len(by_id["stress_ng:cache"]) == 1
    assert by_id["stress_ng:cache"][0]["score"] == 251720.14
    assert by_id["stress_ng:branch"][0]["score"] == 42.0


def test_stressng_benchmark_scores_single_vcpu_emits_multi(tmp_path, monkeypatch):
    stdout = tmp_path / "stdout"
    stdout.write_text(
        json.dumps({"stressors": {"memcpy": {"1": {"bogo_ops_per_sec": 100.0}}}})
    )
    monkeypatch.setattr(
        "sc_crawler.inspector._server_framework_stdout_path",
        lambda server, framework: stdout,
    )
    monkeypatch.setattr(
        "sc_crawler.inspector._server_framework_meta",
        lambda server, framework: {
            "end": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "version": "0.18.12",
            "kernel_version": "6.8.0",
        },
    )
    server = ServerBase(
        vendor_id="aws",
        server_id="t3.micro",
        name="t3.micro",
        api_reference="t3.micro",
        display_name="t3.micro",
        description="test",
        vcpus=1,
        memory_amount=1024,
        storage_size=0,
        status=Status.ACTIVE,
    )
    rows = [
        score
        for score in inspect_server_benchmarks(server)
        if score["benchmark_id"] == "stress_ng:memcpy"
    ]
    assert [row["config"]["cores"] for row in rows] == [
        Parallelism.SINGLE,
        Parallelism.MULTI,
    ]
    assert [row["score"] for row in rows] == [100.0, 100.0]


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
    assert all("observed_at" not in r for r in raw)
    assert all(
        r["environment"]["measured_at"] == "2026-01-01T00:00:00+00:00" for r in raw
    )
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


def test_nvbandwidth_v08_local_copy_and_stacked_bidirectional(tmp_path, monkeypatch):
    scores = _nvbandwidth_scores(
        tmp_path,
        monkeypatch,
        _nvbandwidth_payload(
            [
                _nvbandwidth_testcase(
                    "device_local_copy",
                    matrix=[["728.348", "728.912"]],
                    total=1457.26,
                ),
                # v0.8: both directions and their Total stacked, `sum` is the Total
                _nvbandwidth_testcase(
                    "device_to_device_bidirectional_memcpy_write_ce",
                    matrix=[
                        ["N/A", "52.6138"],
                        ["52.5645", "N/A"],
                        ["N/A", "52.5642"],
                        ["52.6112", "N/A"],
                        ["N/A", "105.178"],
                        ["105.176", "N/A"],
                    ],
                    total=210.354,
                ),
            ],
            driver="595.45.04",
            cuda=13020,
            version="v0.8",
        ),
    )
    assert scores["nvbandwidth:slot:local_copy"]["score"] == 1457.26 / 2
    assert scores["nvbandwidth:p2p:duplex"]["score"] == 210.354 / 2 / 2
    environment = scores["nvbandwidth:slot:local_copy"]["environment"]
    assert environment["gpu_count"] == 2
    assert environment["nvbandwidth_version"] == "v0.8"
    assert environment["p2p_supported"] is True


@pytest.mark.parametrize(
    "end,expected",
    [
        # sc-inspector records naive timestamps in UTC
        ("2024-07-03T14:05:37.725920", "2024-07-03T14:05:37.725920+00:00"),
        ("2024-07-03T16:05:37+02:00", "2024-07-03T14:05:37+00:00"),
    ],
)
def test_measured_at_is_utc(monkeypatch, end, expected):
    monkeypatch.setattr(
        "sc_crawler.inspector._server_framework_meta",
        lambda server, framework: {"end": end},
    )
    server = ServerBase.model_construct(vendor_id="aws", server_id="m5.large")
    assert _measured_at(server, "lscpu") == expected


@pytest.mark.parametrize(
    "meta,expected",
    [
        (
            {
                "start": "2024-09-21T17:37:40.340294",
                "end": "2024-09-21T17:38:00.020936",
            },
            {"duration": 19.7},
        ),
        # mixed naive (UTC) and tz-aware timestamps
        (
            {"start": "2024-09-21T17:37:40", "end": "2024-09-21T19:38:00+02:00"},
            {"duration": 20.0},
        ),
        ({"end": "2024-09-21T17:38:00"}, {}),
    ],
)
def test_duration(monkeypatch, meta, expected):
    monkeypatch.setattr(
        "sc_crawler.inspector._server_framework_meta",
        lambda server, framework: meta,
    )
    server = ServerBase.model_construct(vendor_id="aws", server_id="m5.large")
    assert _duration(server, "lscpu") == expected
