"""Workload profile score computation and database persistence.

This module computes precomputed compound benchmark scores for all servers
across all vendors and stores them as synthetic BenchmarkScore rows.
"""

from __future__ import annotations

from collections import defaultdict
from math import log2
from statistics import median
from typing import TYPE_CHECKING, Any

from sqlalchemy import update
from sqlmodel import Session, select

from .insert import insert_items
from .table_fields import (
    BenchmarkComponentAggregationMethod,
    BenchmarkComponentMissingPolicy,
    BenchmarkComponentNormalizationMethod,
    ScoreComponent,
    Status,
    WorkloadScoreBreakdown,
)
from .tables import Benchmark, BenchmarkScore, Server, Vendor
from .workload_profiles import WORKLOADS, BenchmarkEntry, Workload

if TYPE_CHECKING:
    pass

# the only supported aggregation and normalization methods right now
_AGGREGATION = BenchmarkComponentAggregationMethod.WEIGHTED_GEOMETRIC_MEAN
_NORMALIZATION = BenchmarkComponentNormalizationMethod.MEDIAN_RATIO


def _round_sigfigs(value: float | None, *, sig: int) -> float | None:
    """Round *value* to *sig* significant figures."""
    if value is None:
        return None
    return float(f"{value:.{sig}g}")


def _component_impact_pct(
    component: ScoreComponent,
    aggregation: BenchmarkComponentAggregationMethod,
    normalization: BenchmarkComponentNormalizationMethod,
) -> float | None:
    """Return approximate per-component impact on the workload score, in percent."""
    if component.normalized is None or component.weight_share <= 0:
        return None
    if (
        aggregation == BenchmarkComponentAggregationMethod.WEIGHTED_GEOMETRIC_MEAN
        and normalization == BenchmarkComponentNormalizationMethod.MEDIAN_RATIO
    ):
        return (component.normalized**component.weight_share - 1) * 100
    raise NotImplementedError(
        "component impact not implemented for "
        f"aggregation={aggregation!r}, normalization={normalization!r}"
    )


def _config_matches(row_config: dict, filter_cfg: dict[str, Any] | None) -> bool:
    """Return True if *row_config* satisfies every key in *filter_cfg*.

    Numeric comparisons tolerate small floating-point differences.
    """
    if not filter_cfg:
        return True
    for key, expected in filter_cfg.items():
        actual = row_config.get(key)
        if actual is None:
            return False
        if isinstance(expected, float) and isinstance(actual, (int, float)):
            if abs(float(actual) - expected) > 1e-6:
                return False
        elif isinstance(expected, int) and isinstance(actual, (int, float)):
            if int(actual) != expected:
                return False
        elif actual != expected:
            return False
    return True


def _collect_benchmark_ids(workload_keys: list[str]) -> list[str]:
    """Return a deduplicated list of benchmark IDs needed for the given workloads."""
    seen: set[str] = set()
    result: list[str] = []
    for w in workload_keys:
        for entry in WORKLOADS[w].benchmarks:
            if entry.benchmark_id not in seen:
                seen.add(entry.benchmark_id)
                result.append(entry.benchmark_id)
    return result


def _collect_entries(workload_keys: list[str]) -> list[BenchmarkEntry]:
    """Return a flat list of all BenchmarkEntry objects across the given workloads.

    The ordering is significant: scoring uses the list index as a stable global
    entry index for per-benchmark median tracking and must receive this list in the
    same order.
    """
    entries: list[BenchmarkEntry] = []
    for w in workload_keys:
        entries.extend(WORKLOADS[w].benchmarks)
    return entries


def _load_benchmark_metadata(session: Session) -> dict[str, bool]:
    """Return a mapping of benchmark_id -> higher_is_better for all active benchmarks."""
    rows = session.exec(
        select(Benchmark.benchmark_id, Benchmark.higher_is_better).where(
            Benchmark.status == Status.ACTIVE
        )
    ).all()
    return {bid: bool(hib) for bid, hib in rows}


def _load_scores(
    session: Session,
    benchmark_ids: list[str],
    entries: list[BenchmarkEntry],
    benchmark_meta: dict[str, bool],
) -> tuple[
    dict[tuple[str, str], dict],  # per-server data keyed by (vendor_id, server_id)
    dict[int, float],  # per-benchmark median per entry index
]:
    """Load raw benchmark scores from the DB and build per-server structures.

    For each (server, entry) pair, keeps the best score according to
    higher_is_better when multiple rows match the same config filter.
    Fleet medians per entry are derived in a second pass from the finalised
    best scores, so intermediate values from duplicate raw rows never skew
    the reference baseline.
    """
    if not benchmark_ids:
        return {}, {}

    rows = session.exec(
        select(
            BenchmarkScore.vendor_id,
            Vendor.name,
            BenchmarkScore.server_id,
            Server.name,
            BenchmarkScore.benchmark_id,
            BenchmarkScore.config,
            BenchmarkScore.score,
        )
        .join(
            Server,
            (Server.vendor_id == BenchmarkScore.vendor_id)
            & (Server.server_id == BenchmarkScore.server_id),
        )
        .join(Vendor, Vendor.vendor_id == BenchmarkScore.vendor_id)
        .where(
            BenchmarkScore.status == Status.ACTIVE,
            BenchmarkScore.benchmark_id.in_(benchmark_ids),
        )
    ).all()

    bid_to_entries: dict[str, list[int]] = defaultdict(list)
    for idx, e in enumerate(entries):
        bid_to_entries[e.benchmark_id].append(idx)

    per_server: dict[tuple[str, str], dict] = {}

    for vendor_id, vendor_name, server_id, server_name, b_id, config, score in rows:
        if b_id not in bid_to_entries:
            continue

        score_val = float(score)
        server_key = (vendor_id, server_id)

        for entry_idx in bid_to_entries[b_id]:
            entry = entries[entry_idx]
            if not _config_matches(config or {}, entry.config_filter):
                continue

            if server_key not in per_server:
                per_server[server_key] = {
                    "vendor_id": vendor_id,
                    "vendor_name": vendor_name,
                    "server_id": server_id,
                    "server_name": server_name,
                    "scores": {},
                }

            srv = per_server[server_key]
            higher = benchmark_meta.get(b_id, True)
            prev = srv["scores"].get(entry_idx)
            if prev is None:
                srv["scores"][entry_idx] = score_val
            else:
                srv["scores"][entry_idx] = (
                    max(prev, score_val) if higher else min(prev, score_val)
                )

    values_by_entry: dict[int, list[float]] = defaultdict(list)
    for server_data in per_server.values():
        for entry_idx, val in server_data["scores"].items():
            values_by_entry[entry_idx].append(val)

    entry_medians = {
        entry_idx: median(values) for entry_idx, values in values_by_entry.items()
    }
    return per_server, entry_medians


def _normalise(raw: float, fleet_median: float, higher_is_better: bool) -> float | None:
    """Normalise *raw* to a log2 ratio to the per-benchmark median, or None if invalid."""
    if raw <= 0 or fleet_median <= 0:
        return None
    ratio = raw / fleet_median if higher_is_better else fleet_median / raw
    return log2(ratio)


def _component_note_for_invalid(raw: float | None) -> str | None:
    if raw is None:
        return None
    return f"invalid value: {raw}"


def _compute_workload_score_rows(
    per_server: dict[tuple[str, str], dict],
    entry_medians: dict[int, float],
    benchmark_meta: dict[str, bool],
    workload_keys: list[str],
) -> list[dict]:
    """Compute workload-profile score rows as BenchmarkScore-compatible dicts.

    Returns one dict per (vendor_id, server_id, workload_key) combination
    that has at least one contributing benchmark score.
    """
    rows: list[dict] = []

    for workload_key in workload_keys:
        w_def: Workload = WORKLOADS[workload_key]
        w_entries = w_def.benchmarks

        global_start = 0
        for w in workload_keys:
            if w == workload_key:
                break
            global_start += len(WORKLOADS[w].benchmarks)

        w_entry_indices = list(range(global_start, global_start + len(w_entries)))

        for server_data in per_server.values():
            log_weighted_sum = 0.0
            total_weight = 0.0
            missing_labels: list[str] = []
            suppressed = False
            breakdown_components: list[ScoreComponent] = []

            for local_i, global_i in enumerate(w_entry_indices):
                entry = w_entries[local_i]
                raw = server_data["scores"].get(global_i)
                fleet_median = entry_medians.get(global_i)
                higher = benchmark_meta.get(entry.benchmark_id, True)

                norm: float | None = None
                component_note: str | None = None

                if raw is not None and fleet_median is not None:
                    norm = _normalise(raw, fleet_median, higher)
                    if norm is None:
                        component_note = _component_note_for_invalid(raw)

                if norm is not None:
                    log_weighted_sum += norm * entry.weight
                    total_weight += entry.weight
                    normalized = 2**norm
                    breakdown_components.append(
                        ScoreComponent(
                            label=entry.label,
                            weight=entry.weight,
                            weight_share=0.0,  # filled after total_weight known
                            raw=_round_sigfigs(raw, sig=4),
                            reference=_round_sigfigs(fleet_median, sig=4),
                            normalized=_round_sigfigs(normalized, sig=3),
                            higher_is_better=higher,
                            note=None,
                        )
                    )
                    continue

                policy = entry.on_missing
                if policy == BenchmarkComponentMissingPolicy.REQUIRE:
                    suppressed = True
                    breakdown_components.append(
                        ScoreComponent(
                            label=entry.label,
                            weight=entry.weight,
                            weight_share=0.0,
                            raw=_round_sigfigs(raw, sig=4),
                            reference=_round_sigfigs(fleet_median, sig=4),
                            normalized=None,
                            higher_is_better=higher,
                            note="required component missing",
                        )
                    )
                    break

                if policy == BenchmarkComponentMissingPolicy.PENALIZE:
                    penalty = entry.effective_penalty()
                    norm = log2(penalty)
                    log_weighted_sum += norm * entry.weight
                    total_weight += entry.weight
                    breakdown_components.append(
                        ScoreComponent(
                            label=entry.label,
                            weight=entry.weight,
                            weight_share=0.0,
                            raw=_round_sigfigs(raw, sig=4),
                            reference=_round_sigfigs(fleet_median, sig=4),
                            normalized=_round_sigfigs(penalty, sig=3),
                            higher_is_better=higher,
                            note="penalized: no usable measurement",
                        )
                    )
                    continue

                # IGNORE (default)
                missing_labels.append(entry.label)
                breakdown_components.append(
                    ScoreComponent(
                        label=entry.label,
                        weight=entry.weight,
                        weight_share=0.0,
                        raw=_round_sigfigs(raw, sig=4),
                        reference=_round_sigfigs(fleet_median, sig=4),
                        normalized=None,
                        higher_is_better=higher,
                        note=component_note,
                    )
                )

            if suppressed or total_weight <= 0:
                continue

            for component in breakdown_components:
                if component.normalized is not None:
                    component.weight_share = component.weight / total_weight
                    component.impact = _round_sigfigs(
                        _component_impact_pct(
                            component,
                            _AGGREGATION,
                            _NORMALIZATION,
                        ),
                        sig=3,
                    )

            score = _round_sigfigs(2 ** (log_weighted_sum / total_weight), sig=3)

            note: str | None = None
            if missing_labels:
                note = (
                    "Partial coverage: missing component benchmark(s): "
                    + ", ".join(missing_labels)
                    + "."
                )

            rows.append(
                {
                    "vendor_id": server_data["vendor_id"],
                    "server_id": server_data["server_id"],
                    "benchmark_id": f"workload_profile:{workload_key}",
                    "config": {},
                    "framework_version": w_def.version,
                    "score": score,
                    "note": note,
                    "score_breakdown": WorkloadScoreBreakdown(
                        aggregation=_AGGREGATION,
                        normalization=_NORMALIZATION,
                        coverage=total_weight,
                        components=breakdown_components,
                    ),
                }
            )

    return rows


def recompute_workload_profiles(session: Session) -> int:
    """Recompute workload-profile scores for all servers and persist them.

    Marks all existing workload-profile BenchmarkScore rows inactive, then
    loads all active raw benchmark scores from the database (excluding
    workload-profile rows to avoid circularity), computes composite scores vs
    per-benchmark medians across all vendors, and inserts fresh rows.

    Args:
        session: Active SQLModel session connected to the crawler database.

    Returns:
        The number of workload-profile rows inserted.
    """
    workload_keys = list(WORKLOADS.keys())
    benchmark_ids = _collect_benchmark_ids(workload_keys)
    entries = _collect_entries(workload_keys)

    benchmark_meta = _load_benchmark_metadata(session)
    per_server, entry_medians = _load_scores(
        session, benchmark_ids, entries, benchmark_meta
    )

    if not per_server:
        return 0

    profile_rows = _compute_workload_score_rows(
        per_server, entry_medians, benchmark_meta, workload_keys
    )

    if not profile_rows:
        return 0

    session.exec(
        update(BenchmarkScore)
        .where(BenchmarkScore.benchmark_id.like("workload_profile:%"))
        .values(status=Status.INACTIVE)
    )
    insert_items(BenchmarkScore, profile_rows, session=session)
    return len(profile_rows)
