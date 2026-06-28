import math

import pytest

from sc_crawler.lookup import benchmarks
from sc_crawler.table_fields import BenchmarkComponentMissingPolicy
from sc_crawler.workload_profile_scores import (
    _compute_workload_score_rows,
    _normalise,
)
from sc_crawler.workload_profiles import WORKLOADS, BenchmarkEntry, Workload


@pytest.fixture
def test_workload(monkeypatch):
    workload = Workload(
        name="Test",
        version="2.0",
        rationale="test",
        benchmarks=[
            BenchmarkEntry(benchmark_id="bench:a", weight=0.6, label="metric-a"),
            BenchmarkEntry(benchmark_id="bench:b", weight=0.4, label="metric-b"),
        ],
    )
    monkeypatch.setitem(WORKLOADS, "test", workload)
    return workload


def test_normalise_higher_is_better():
    assert _normalise(200.0, 100.0, True) == pytest.approx(1.0)
    assert _normalise(50.0, 100.0, True) == pytest.approx(-1.0)


def test_normalise_lower_is_better():
    assert _normalise(50.0, 100.0, False) == pytest.approx(1.0)
    assert _normalise(200.0, 100.0, False) == pytest.approx(-1.0)


def test_normalise_invalid_values():
    assert _normalise(0.0, 100.0, True) is None
    assert _normalise(100.0, 0.0, True) is None
    assert _normalise(-1.0, 100.0, True) is None


def test_compute_workload_score_rows_at_fleet_median(test_workload):
    per_server = {
        ("v1", "s1"): {
            "vendor_id": "v1",
            "server_id": "s1",
            "scores": {0: 100.0, 1: 50.0},
        }
    }
    rows = _compute_workload_score_rows(
        per_server,
        {0: 100.0, 1: 50.0},
        {"bench:a": True, "bench:b": True},
        ["test"],
    )

    assert len(rows) == 1
    assert rows[0]["score"] == pytest.approx(1.0)
    assert rows[0]["note"] is None
    breakdown = rows[0]["score_breakdown"]
    assert breakdown.coverage == pytest.approx(1.0)
    assert len(breakdown.components) == 2
    assert all(c.normalized is not None for c in breakdown.components)


def test_compute_workload_score_rows_twice_fleet_median(monkeypatch):
    monkeypatch.setitem(
        WORKLOADS,
        "test",
        Workload(
            name="Test",
            version="2.0",
            rationale="test",
            benchmarks=[
                BenchmarkEntry(benchmark_id="bench:a", weight=0.5, label="metric-a"),
                BenchmarkEntry(benchmark_id="bench:b", weight=0.5, label="metric-b"),
            ],
        ),
    )
    per_server = {
        ("v1", "s1"): {
            "vendor_id": "v1",
            "server_id": "s1",
            "scores": {0: 200.0, 1: 160.0},
        }
    }
    rows = _compute_workload_score_rows(
        per_server,
        {0: 100.0, 1: 80.0},
        {"bench:a": True, "bench:b": True},
        ["test"],
    )

    assert rows[0]["score"] == pytest.approx(2.0)


def test_compute_workload_score_rows_partial_coverage(test_workload):
    per_server = {
        ("v1", "s1"): {
            "vendor_id": "v1",
            "server_id": "s1",
            "scores": {0: 200.0},
        }
    }
    rows = _compute_workload_score_rows(
        per_server,
        {0: 100.0, 1: 50.0},
        {"bench:a": True, "bench:b": True},
        ["test"],
    )

    assert rows[0]["score"] == pytest.approx(2.0)
    assert "metric-b" in rows[0]["note"]
    breakdown = rows[0]["score_breakdown"]
    assert breakdown.coverage == pytest.approx(0.6)
    ignored = [c for c in breakdown.components if c.normalized is None]
    assert len(ignored) == 1
    assert ignored[0].weight_share == 0.0
    contributing = [c for c in breakdown.components if c.normalized is not None]
    assert sum(c.weight_share for c in contributing) == pytest.approx(1.0)


def test_compute_workload_score_rows_lower_is_better(monkeypatch):
    monkeypatch.setitem(
        WORKLOADS,
        "test",
        Workload(
            name="Test",
            version="2.0",
            rationale="test",
            benchmarks=[
                BenchmarkEntry(
                    benchmark_id="bench:latency", weight=1.0, label="latency"
                ),
            ],
        ),
    )
    per_server = {
        ("v1", "s1"): {
            "vendor_id": "v1",
            "server_id": "s1",
            "scores": {0: 50.0},
        }
    }
    rows = _compute_workload_score_rows(
        per_server,
        {0: 100.0},
        {"bench:latency": False},
        ["test"],
    )

    assert rows[0]["score"] == pytest.approx(2.0)


def test_compute_workload_score_rows_skips_zero_median(monkeypatch):
    monkeypatch.setitem(
        WORKLOADS,
        "test",
        Workload(
            name="Test",
            version="2.0",
            rationale="test",
            benchmarks=[
                BenchmarkEntry(benchmark_id="bench:a", weight=0.5, label="metric-a"),
                BenchmarkEntry(benchmark_id="bench:b", weight=0.5, label="metric-b"),
            ],
        ),
    )
    per_server = {
        ("v1", "s1"): {
            "vendor_id": "v1",
            "server_id": "s1",
            "scores": {0: 100.0, 1: 10.0},
        }
    }
    rows = _compute_workload_score_rows(
        per_server,
        {0: 100.0, 1: 0.0},
        {"bench:a": True, "bench:b": True},
        ["test"],
    )

    assert rows[0]["score"] == pytest.approx(1.0)
    assert "metric-b" in rows[0]["note"]


def test_compute_workload_score_rows_weighted_geometric_mean(monkeypatch):
    monkeypatch.setitem(
        WORKLOADS,
        "test",
        Workload(
            name="Test",
            version="2.0",
            rationale="test",
            benchmarks=[
                BenchmarkEntry(benchmark_id="bench:a", weight=0.75, label="metric-a"),
                BenchmarkEntry(benchmark_id="bench:b", weight=0.25, label="metric-b"),
            ],
        ),
    )
    per_server = {
        ("v1", "s1"): {
            "vendor_id": "v1",
            "server_id": "s1",
            "scores": {0: 200.0, 1: 100.0},
        }
    }
    rows = _compute_workload_score_rows(
        per_server,
        {0: 100.0, 1: 100.0},
        {"bench:a": True, "bench:b": True},
        ["test"],
    )

    expected_log_avg = (0.75 * math.log2(2.0) + 0.25 * math.log2(1.0)) / 1.0
    assert rows[0]["score"] == pytest.approx(2**expected_log_avg)
    breakdown = rows[0]["score_breakdown"]
    product = 1.0
    for c in breakdown.components:
        if c.normalized is not None:
            product *= c.normalized**c.weight_share
    assert product == pytest.approx(rows[0]["score"], rel=1e-6)


def test_compute_workload_score_rows_penalize(monkeypatch):
    monkeypatch.setitem(
        WORKLOADS,
        "test",
        Workload(
            name="Test",
            version="2.0",
            rationale="test",
            benchmarks=[
                BenchmarkEntry(benchmark_id="bench:a", weight=0.5, label="metric-a"),
                BenchmarkEntry(
                    benchmark_id="bench:b",
                    weight=0.5,
                    label="metric-b",
                    on_missing=BenchmarkComponentMissingPolicy.PENALIZE,
                    penalty=1e-4,
                ),
            ],
        ),
    )
    per_server = {
        ("v1", "s1"): {
            "vendor_id": "v1",
            "server_id": "s1",
            "scores": {0: 200.0},
        }
    }
    rows = _compute_workload_score_rows(
        per_server,
        {0: 100.0, 1: 50.0},
        {"bench:a": True, "bench:b": True},
        ["test"],
    )

    assert len(rows) == 1
    breakdown = rows[0]["score_breakdown"]
    assert breakdown.coverage == pytest.approx(1.0)
    penalized = breakdown.components[1]
    assert penalized.normalized == pytest.approx(1e-4)
    assert penalized.weight_share == pytest.approx(0.5)
    assert penalized.note == "penalized: no usable measurement"
    assert rows[0]["note"] is None
    assert rows[0]["score"] < 2.0


def test_compute_workload_score_rows_require_suppresses_row(monkeypatch):
    monkeypatch.setitem(
        WORKLOADS,
        "test",
        Workload(
            name="Test",
            version="2.0",
            rationale="test",
            benchmarks=[
                BenchmarkEntry(
                    benchmark_id="bench:a",
                    weight=0.5,
                    label="metric-a",
                    on_missing=BenchmarkComponentMissingPolicy.REQUIRE,
                ),
                BenchmarkEntry(benchmark_id="bench:b", weight=0.5, label="metric-b"),
            ],
        ),
    )
    per_server = {
        ("v1", "s1"): {
            "vendor_id": "v1",
            "server_id": "s1",
            "scores": {1: 50.0},
        }
    }
    rows = _compute_workload_score_rows(
        per_server,
        {0: 100.0, 1: 50.0},
        {"bench:a": True, "bench:b": True},
        ["test"],
    )

    assert rows == []


def test_benchmark_source_descriptors():
    by_id = {b.benchmark_id: b for b in benchmarks}

    for workload_name, workload in WORKLOADS.items():
        bench = by_id[f"workload_profile:{workload_name}"]
        assert bench.source.kind == "compound"
        assert bench.source.aggregation.value == "weighted_geometric_mean"
        assert bench.source.normalization.value == "median_ratio"
        assert len(bench.source.components) == len(workload.benchmarks)

    for bid in (
        "static_web:rps-extrapolated",
        "static_web:throughput-extrapolated",
        "redis:rps-extrapolated",
    ):
        bench = by_id[bid]
        assert bench.source.kind == "extrapolated"
        assert bench.source.derived_from

    assert by_id["static_web:rps"].source.kind == "measured"
    assert by_id["static_web:rps"].note is not None


def test_llm_workload_missing_policies():
    llm = WORKLOADS["llm"]
    required = [
        e
        for e in llm.benchmarks
        if e.on_missing == BenchmarkComponentMissingPolicy.REQUIRE
    ]
    penalized = [
        e
        for e in llm.benchmarks
        if e.on_missing == BenchmarkComponentMissingPolicy.PENALIZE
    ]
    assert len(required) == 2
    assert all("Llama 7B" in e.label for e in required)
    assert len(penalized) == 2
    assert all("70B" in e.label for e in penalized)
    for entry in penalized:
        assert "llama-3.3-70b" in entry.config_filter["model"]
