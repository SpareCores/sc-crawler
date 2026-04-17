"""Workload profile score computation and database persistence.

This module computes precomputed compound benchmark scores for all servers
across all vendors and stores them as synthetic BenchmarkScore rows.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import update
from sqlmodel import Session, select

from .insert import insert_items
from .table_fields import Status
from .tables import Benchmark, BenchmarkScore, Server, Vendor
from .workload_profiles import WORKLOADS, BenchmarkEntry, Workload

if TYPE_CHECKING:
    pass


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

    The ordering is significant: `compute_workload_scores` uses the list index
    as a stable global entry index for min/max tracking and must receive this
    list in the same order.
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
    dict[int, tuple[float, float]],  # global (min, max) per entry index
]:
    """Load raw benchmark scores from the DB and build per-server structures.

    For each (server, entry) pair, keeps the best score according to
    higher_is_better when multiple rows match the same config filter.
    The global (min, max) range per entry is derived in a second pass from
    the finalised best scores, so intermediate values from duplicate raw rows
    never skew normalisation.
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

    entry_minmax: dict[int, tuple[float, float]] = {}
    for server_data in per_server.values():
        for entry_idx, val in server_data["scores"].items():
            if entry_idx not in entry_minmax:
                entry_minmax[entry_idx] = (val, val)
            else:
                lo, hi = entry_minmax[entry_idx]
                entry_minmax[entry_idx] = (min(lo, val), max(hi, val))

    return per_server, entry_minmax


def _normalise(raw: float, lo: float, hi: float, higher_is_better: bool) -> float:
    """Normalise *raw* to a [0, 1] scale given the observed global range."""
    if hi == lo:
        return 1.0
    dividend = (raw - lo) if higher_is_better else (hi - raw)
    return dividend / (hi - lo)


def _compute_workload_score_rows(
    per_server: dict[tuple[str, str], dict],
    entry_minmax: dict[int, tuple[float, float]],
    entries: list[BenchmarkEntry],
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

        for server_key, server_data in per_server.items():
            weighted_sum = 0.0
            total_weight = 0.0
            missing_labels: list[str] = []

            for local_i, global_i in enumerate(w_entry_indices):
                entry = w_entries[local_i]
                raw = server_data["scores"].get(global_i)
                if raw is None or global_i not in entry_minmax:
                    missing_labels.append(entry.label)
                    continue

                lo, hi = entry_minmax[global_i]
                higher = benchmark_meta.get(entry.benchmark_id, True)
                norm = _normalise(raw, lo, hi, higher)
                weighted_sum += norm * entry.weight
                total_weight += entry.weight

            if total_weight <= 0:
                continue

            score = weighted_sum / total_weight

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
                }
            )

    return rows


def recompute_workload_profiles(session: Session) -> int:
    """Recompute workload-profile scores for all servers and persist them.

    Marks all existing workload-profile BenchmarkScore rows inactive, then
    loads all active raw benchmark scores from the database (excluding
    workload-profile rows to avoid circularity), computes normalised composite
    scores across all vendors, and inserts fresh rows.

    Args:
        session: Active SQLModel session connected to the crawler database.

    Returns:
        The number of workload-profile rows inserted.
    """
    workload_keys = list(WORKLOADS.keys())
    benchmark_ids = _collect_benchmark_ids(workload_keys)
    entries = _collect_entries(workload_keys)

    benchmark_meta = _load_benchmark_metadata(session)
    per_server, entry_minmax = _load_scores(
        session, benchmark_ids, entries, benchmark_meta
    )

    if not per_server:
        return 0

    profile_rows = _compute_workload_score_rows(
        per_server, entry_minmax, entries, benchmark_meta, workload_keys
    )

    if not profile_rows:
        return 0

    session.execute(
        update(BenchmarkScore)
        .where(BenchmarkScore.benchmark_id.like("workload_profile:%"))
        .values(status=Status.INACTIVE)
    )
    insert_items(BenchmarkScore, profile_rows, session=session)
    return len(profile_rows)
