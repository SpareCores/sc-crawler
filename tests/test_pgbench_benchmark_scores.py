import json
from datetime import datetime, timezone

from sc_crawler.inspector import _pgbench_benchmark_scores
from sc_crawler.table_bases import ServerBase
from sc_crawler.table_fields import Status


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
