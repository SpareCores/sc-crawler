import math

import pytest

from sc_crawler.lookup import benchmarks
from sc_crawler.table_fields import (
    BenchmarkComponentAggregationMethod,
    BenchmarkComponentMissingPolicy,
    BenchmarkComponentNormalizationMethod,
    WorkloadScoreBreakdown,
)
from sc_crawler.workload_profile_scores import (
    _component_impact_pct,
    _compute_workload_score_rows,
    _normalise,
)
from sc_crawler.workload_profiles import (
    WORKLOADS,
    BenchmarkEntry,
    Workload,
    _impact_tooltip,
)


def _reconstruct_score_from_breakdown(breakdown: WorkloadScoreBreakdown) -> float:
    """Rebuild the composite score using the same log-ratio aggregation as production."""
    log_weighted_sum = 0.0
    for component in breakdown.components:
        if component.normalized is None:
            continue
        if component.raw is not None and component.reference is not None:
            norm = _normalise(
                component.raw, component.reference, component.higher_is_better
            )
            assert norm is not None
        else:
            norm = math.log2(component.normalized)
        log_weighted_sum += norm * component.weight
    return 2 ** (log_weighted_sum / breakdown.coverage)


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
    assert _reconstruct_score_from_breakdown(breakdown) == pytest.approx(
        rows[0]["score"], rel=1e-6
    )
    for component in breakdown.components:
        if component.normalized is not None and component.weight_share > 0:
            assert component.impact == pytest.approx(
                (component.normalized**component.weight_share - 1) * 100,
                rel=1e-6,
            )
        else:
            assert component.impact is None


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
    assert _reconstruct_score_from_breakdown(breakdown) == pytest.approx(
        rows[0]["score"], rel=1e-6
    )


def test_compute_workload_score_rows_lower_is_better_reconstruction(monkeypatch):
    monkeypatch.setitem(
        WORKLOADS,
        "test",
        Workload(
            name="Test",
            version="2.0",
            rationale="test",
            benchmarks=[
                BenchmarkEntry(benchmark_id="bench:a", weight=1.0, label="latency"),
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
        {"bench:a": False},
        ["test"],
    )

    breakdown = rows[0]["score_breakdown"]
    component = breakdown.components[0]
    assert component.higher_is_better is False
    assert component.normalized == pytest.approx(2.0)
    assert rows[0]["score"] == pytest.approx(2.0)
    assert _reconstruct_score_from_breakdown(breakdown) == pytest.approx(
        rows[0]["score"], rel=1e-6
    )


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
        assert bench.source.impact_formula == _impact_tooltip(
            bench.source.aggregation,
            bench.source.normalization,
        )

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


def test_benchmark_entry_json_omits_penalty_unless_penalized():
    ignore = BenchmarkEntry(benchmark_id="bench:a", weight=0.5, label="metric-a")
    penalized = BenchmarkEntry(
        benchmark_id="bench:b",
        weight=0.5,
        label="metric-b",
        on_missing=BenchmarkComponentMissingPolicy.PENALIZE,
    )

    assert "penalty" not in ignore.__json__()
    assert penalized.__json__()["penalty"] == 1e-4

    llm = next(
        e
        for e in WORKLOADS["llm"].benchmarks
        if e.on_missing == BenchmarkComponentMissingPolicy.PENALIZE
    )
    serialized = llm.__json__()
    assert serialized["on_missing"] == "penalize"
    assert serialized["penalty"] == 1e-4


def test_create_sc_engine_serializes_typed_json_on_merge(tmp_path):
    from alembic import command
    from sqlmodel import Session

    from sc_crawler.alembic_helpers import alembic_cfg
    from sc_crawler.lookup import benchmarks
    from sc_crawler.utils import create_sc_engine

    engine = create_sc_engine(f"sqlite:///{tmp_path / 'sc-engine-merge.db'}")
    with engine.begin() as conn:
        command.upgrade(alembic_cfg(conn, force_logging=False), "heads")

    benchmark = next(b for b in benchmarks if b.benchmark_id == "workload_profile:web")
    with Session(engine) as session:
        session.merge(benchmark)
        session.commit()


def test_benchmark_merge_backfills_null_measured_source(tmp_path):
    from alembic import command
    from sqlalchemy import text
    from sqlmodel import Session

    from sc_crawler.alembic_helpers import alembic_cfg
    from sc_crawler.utils import create_sc_engine

    engine = create_sc_engine(f"sqlite:///{tmp_path / 'benchmark-source-merge.db'}")
    with engine.begin() as conn:
        command.upgrade(alembic_cfg(conn, force_logging=False), "heads")

    with Session(engine) as session:
        benchmark = next(b for b in benchmarks if b.benchmark_id == "bogomips")
        session.merge(benchmark)
        session.commit()

    with engine.connect() as conn:
        conn.execute(
            text("UPDATE benchmark SET source = NULL WHERE benchmark_id='bogomips'")
        )
        conn.commit()

    with Session(engine) as session:
        benchmark = next(b for b in benchmarks if b.benchmark_id == "bogomips")
        session.merge(benchmark)
        session.commit()

    with engine.connect() as conn:
        source = conn.execute(
            text("SELECT source FROM benchmark WHERE benchmark_id='bogomips'")
        ).scalar()
        assert source == '{"kind": "measured"}'


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
    assert all("SmolLM-135M" in e.label for e in required)
    assert len(penalized) == 4
    llama_7b = [e for e in penalized if "Llama 7B" in e.label]
    llama_70b = [e for e in penalized if "70B" in e.label]
    assert len(llama_7b) == 2
    assert len(llama_70b) == 2
    for entry in llama_7b:
        assert "llama-7b" in entry.config_filter["model"]
    for entry in llama_70b:
        assert "Llama-3.3-70B" in entry.config_filter["model"]


def test_impact_tooltip_geomean_median_ratio():
    tooltip = _impact_tooltip(
        BenchmarkComponentAggregationMethod.WEIGHTED_GEOMETRIC_MEAN,
        BenchmarkComponentNormalizationMethod.MEDIAN_RATIO,
    )
    assert "median on all parts" in tooltip
    assert "don't add" in tooltip


def test_component_impact_pct_geomean_median_ratio():
    from sc_crawler.table_fields import ScoreComponent

    component = ScoreComponent(
        label="metric-a",
        weight=0.1,
        weight_share=0.1,
        normalized=3.0,
    )
    assert _component_impact_pct(
        component,
        BenchmarkComponentAggregationMethod.WEIGHTED_GEOMETRIC_MEAN,
        BenchmarkComponentNormalizationMethod.MEDIAN_RATIO,
    ) == pytest.approx((3.0**0.1 - 1) * 100, rel=1e-6)
    assert (
        _component_impact_pct(
            ScoreComponent(
                label="metric-b",
                weight=0.1,
                weight_share=0.1,
                normalized=None,
            ),
            BenchmarkComponentAggregationMethod.WEIGHTED_GEOMETRIC_MEAN,
            BenchmarkComponentNormalizationMethod.MEDIAN_RATIO,
        )
        is None
    )


def test_impact_unsupported_method_pair_raises():
    from sc_crawler.table_fields import ScoreComponent

    class _Unsupported:
        def __repr__(self) -> str:
            return "unsupported"

    unsupported = _Unsupported()
    with pytest.raises(NotImplementedError, match="impact tooltip not implemented"):
        _impact_tooltip(
            unsupported,  # type: ignore[arg-type]
            BenchmarkComponentNormalizationMethod.MEDIAN_RATIO,
        )
    with pytest.raises(NotImplementedError, match="component impact not implemented"):
        _component_impact_pct(
            ScoreComponent(
                label="metric-a",
                weight=0.5,
                weight_share=0.5,
                normalized=2.0,
            ),
            unsupported,  # type: ignore[arg-type]
            BenchmarkComponentNormalizationMethod.MEDIAN_RATIO,
        )
