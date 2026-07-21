from sc_crawler.insert import _dedupe_items, _primary_key_tuple
from sc_crawler.table_bases import BenchmarkScoreBase, DatabaseBase, DatabasePriceBase
from sc_crawler.table_fields import Allocation, DatabaseEngine, PriceUnit, Status


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


def test_dedupe_items_collapses_duplicate_database_prices():
    base = {
        "vendor_id": "aws",
        "region_id": "us-east-1",
        "database_id": "db.t3.micro",
        "allocation": Allocation.ONDEMAND,
        "unit": PriceUnit.HOUR,
        "price": 0.02,
        "price_upfront": 0,
        "price_tiered": [],
        "currency": "USD",
        "status": Status.ACTIVE,
    }
    items = [
        base,
        {**base, "price": 0.03},
    ]
    validated = [DatabasePriceBase.model_validate(item).model_dump() for item in items]
    deduped = _dedupe_items(
        validated,
        ["vendor_id", "region_id", "database_id", "allocation"],
    )
    assert len(deduped) == 1
    assert deduped[0]["price"] == 0.03


def test_database_base_round_trip():
    item = DatabaseBase.model_validate(
        {
            "vendor_id": "gcp",
            "database_id": "db-n1-standard-4",
            "name": "db-n1-standard-4",
            "api_reference": "db-n1-standard-4",
            "display_name": "db-n1-standard-4",
            "description": "PostgreSQL Cloud SQL N1 Standard (4 vCPUs, 15 GB RAM)",
            "engine": DatabaseEngine.POSTGRESQL,
            "engine_versions": ["15", "16"],
            "storage_size": None,
            "status": Status.ACTIVE,
        }
    )
    assert item.engine_versions == ["15", "16"]
    assert item.storage_size is None
