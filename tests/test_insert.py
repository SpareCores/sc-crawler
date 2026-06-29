from sc_crawler.insert import _dedupe_items, _primary_key_tuple
from sc_crawler.table_bases import BenchmarkScoreBase
from sc_crawler.table_fields import Status


def test_primary_key_tuple_normalizes_json_config_key_order():
    item_a = {"config": {"size": 1.0, "operation": "rd"}}
    item_b = {"config": {"operation": "rd", "size": 1.0}}
    keys = ("vendor_id", "server_id", "benchmark_id", "config")

    assert _primary_key_tuple(item_a, list(keys)) == _primary_key_tuple(
        item_b, list(keys)
    )


def test_dedupe_items_collapses_duplicate_benchmark_scores():
    base = {
        "vendor_id": "aws",
        "server_id": "t3.micro",
        "benchmark_id": "bw_mem",
        "framework_version": None,
        "kernel_version": None,
        "score": 1.0,
        "score_breakdown": None,
        "note": None,
        "status": Status.ACTIVE,
    }
    items = [
        {**base, "config": {"size": 1.0, "operation": "rd"}},
        {**base, "config": {"operation": "rd", "size": 1.0}, "score": 2.0},
    ]

    validated = [BenchmarkScoreBase.model_validate(item).model_dump() for item in items]
    deduped = _dedupe_items(
        validated,
        ["vendor_id", "server_id", "benchmark_id", "config"],
    )

    assert len(deduped) == 1
    assert deduped[0]["score"] == 2.0
