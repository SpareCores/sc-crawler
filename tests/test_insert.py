from datetime import UTC, datetime
from json import loads

from alembic import command
from sqlmodel import Session, select

from sc_crawler.alembic_helpers import alembic_cfg
from sc_crawler.insert import (
    _dedupe_items,
    _primary_key_tuple,
    insert_items,
    merge_changed_item,
    upsert_changed_items,
)
from sc_crawler.table_bases import (
    BenchmarkScoreBase,
    DatabaseBase,
    DatabasePriceBase,
    row_key,
)
from sc_crawler.table_fields import (
    Allocation,
    DatabaseEngine,
    DatabaseHaLevel,
    DatabaseHaStrategy,
    DatabaseSecurityFeature,
    DatabaseWireProtocol,
    PriceUnit,
    ResourceType,
    Status,
)
from sc_crawler.tables import BenchmarkScore, Country, Vendor
from sc_crawler.utils import create_sc_engine, get_row_by_pk


def test_primary_key_tuple_normalizes_json_config_key_order():
    item_a = {"config": {"size": 1.0, "operation": "rd"}}
    item_b = {"config": {"operation": "rd", "size": 1.0}}
    keys = ("vendor_id", "resource_type", "resource_id", "benchmark_id", "config")

    assert _primary_key_tuple(item_a, list(keys)) == _primary_key_tuple(
        item_b, list(keys)
    )


def test_dedupe_items_collapses_duplicate_benchmark_scores():
    base = {
        "vendor_id": "aws",
        "server_id": "t3.micro",
        "benchmark_id": "bw_mem",
        "framework_version": None,
        "environment": None,
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
        ["vendor_id", "resource_type", "resource_id", "benchmark_id", "config"],
    )

    assert len(deduped) == 1
    assert deduped[0]["score"] == 2.0
    assert deduped[0]["resource_type"] == ResourceType.SERVER
    assert deduped[0]["resource_id"] == "t3.micro"


def test_dedupe_items_collapses_duplicate_database_prices():
    base = {
        "vendor_id": "aws",
        "region_id": "us-east-1",
        "database_id": "db.t3.micro",
        "allocation": Allocation.ONDEMAND,
        "ha": DatabaseHaLevel.SINGLE_ZONE,
        "ha_strategy": DatabaseHaStrategy.NONE,
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
        ["vendor_id", "region_id", "database_id", "allocation", "ha", "ha_strategy"],
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
            "wire_protocol": DatabaseWireProtocol.POSTGRESQL,
            "engine_versions": ["15", "16"],
            "security_features": ["ip-filtering"],
            "storage_size": None,
            "status": Status.ACTIVE,
        }
    )
    assert item.engine_versions == ["15", "16"]
    assert item.wire_protocol == DatabaseWireProtocol.POSTGRESQL
    assert item.security_features == [DatabaseSecurityFeature.IP_FILTERING]
    assert item.storage_size is None
    assert item.api_reference_object is None


def test_database_benchmark_score_via_database_id_key():
    item = BenchmarkScoreBase.model_validate(
        {
            "vendor_id": "gcp",
            "database_id": "db-n1-standard-4",
            "benchmark_id": "pgbench_tps",
            "config": {"scale": 100, "clients": 4},
            "score": 1234.5,
            "status": Status.ACTIVE,
        }
    )
    assert item.resource_type == ResourceType.DATABASE
    assert item.resource_id == "db-n1-standard-4"
    assert item.database_id == "db-n1-standard-4"
    assert item.config == {"clients": 4, "scale": 100}
    assert item.score == 1234.5


def _country_db(tmp_path):
    engine = create_sc_engine(f"sqlite:///{tmp_path / 'insert.db'}")
    with engine.begin() as conn:
        command.upgrade(alembic_cfg(conn, force_logging=False), "heads")
    return engine


def _rows(session, model):
    session.expire_all()
    return {
        row_key(r.model_dump(), model.get_columns()["primary_keys"]): r
        for r in session.exec(select(model))
    }


US = {"country_id": "US", "continent": "North America", "status": Status.ACTIVE}
DE = {"country_id": "DE", "continent": "Europe", "status": Status.ACTIVE}


def test_hash_key_keeps_exact_primary_key_values():
    # sync loads the key back to look up the row, so 1.0 must not become 1
    item = BenchmarkScoreBase.model_validate(
        {
            "vendor_id": "aws",
            "server_id": "a1.2xlarge",
            "benchmark_id": "bw_mem",
            "config": {"operation": "rd", "size": 1.0},
            "score": 1.0,
            "status": Status.ACTIVE,
        }
    ).model_dump()
    (key,) = BenchmarkScore.hash(None, rows=[item]).keys()
    assert loads(key)["config"] == {"operation": "rd", "size": 1.0}
    assert isinstance(loads(key)["config"]["size"], float)


def test_sync_lookup_finds_row_with_whole_float_in_json_pk(tmp_path):
    engine = _country_db(tmp_path)
    score = {
        "vendor_id": "aws",
        "server_id": "a1.2xlarge",
        "benchmark_id": "bw_mem",
        "config": {"operation": "rd", "size": 1.0},
        "score": 1.0,
        "status": Status.ACTIVE,
    }
    with Session(engine) as session:
        insert_items(BenchmarkScore, [score], session=session)
        session.commit()
        (key,) = BenchmarkScore.hash(session).keys()
        assert get_row_by_pk(session, BenchmarkScore, loads(key)).score == 1.0


def test_hash_treats_whole_number_floats_as_equal():
    whole = {"country_id": "US", "continent": "North America", "n": 0.0}
    integer = {"country_id": "US", "continent": "North America", "n": 0}
    fraction = {"country_id": "US", "continent": "North America", "n": 0.5}
    assert Country.hash(None, rows=[whole]) == Country.hash(None, rows=[integer])
    assert Country.hash(None, rows=[whole]) != Country.hash(None, rows=[fraction])


def test_upsert_changed_items_lifecycle(tmp_path):
    engine = _country_db(tmp_path)
    with Session(engine) as session:
        stats = upsert_changed_items(Country, [dict(US), dict(DE)], session=session)
        session.commit()
        assert stats == {"new": 2, "changed": 0, "unchanged": 0, "deactivated": 0}
        first = {k: r.observed_at for k, r in _rows(session, Country).items()}

        # unchanged rows are not rewritten
        stats = upsert_changed_items(Country, [dict(US), dict(DE)], session=session)
        session.commit()
        assert stats == {"new": 0, "changed": 0, "unchanged": 2, "deactivated": 0}
        assert {k: r.observed_at for k, r in _rows(session, Country).items()} == first

        # changed row gets a new observed_at, missing row is deactivated with a new one
        stats = upsert_changed_items(
            Country, [{**US, "continent": "Americas"}], session=session
        )
        session.commit()
        assert stats == {"new": 0, "changed": 1, "unchanged": 0, "deactivated": 1}
        rows = _rows(session, Country)
        us, de = rows['{"country_id": "US"}'], rows['{"country_id": "DE"}']
        assert us.continent == "Americas"
        assert us.observed_at != first['{"country_id": "US"}']
        assert de.status == Status.INACTIVE
        assert de.observed_at != first['{"country_id": "DE"}']
        inactive_since = de.observed_at

        # already inactive rows are left alone
        stats = upsert_changed_items(
            Country, [{**US, "continent": "Americas"}], session=session
        )
        session.commit()
        assert stats == {"new": 0, "changed": 0, "unchanged": 1, "deactivated": 0}
        assert (
            _rows(session, Country)['{"country_id": "DE"}'].observed_at
            == inactive_since
        )

        # reappearing row is reactivated with a new observed_at
        stats = upsert_changed_items(
            Country, [{**US, "continent": "Americas"}, dict(DE)], session=session
        )
        session.commit()
        assert stats == {"new": 0, "changed": 1, "unchanged": 1, "deactivated": 0}
        de = _rows(session, Country)['{"country_id": "DE"}']
        assert de.status == Status.ACTIVE
        assert de.observed_at != inactive_since


def test_upsert_changed_items_respects_scope(tmp_path):
    engine = _country_db(tmp_path)
    with Session(engine) as session:
        upsert_changed_items(Country, [dict(US), dict(DE)], session=session)
        session.commit()
        stats = upsert_changed_items(
            Country, [dict(US)], Country.continent == "North America", session=session
        )
        session.commit()
        assert stats["deactivated"] == 0
        assert _rows(session, Country)['{"country_id": "DE"}'].status == Status.ACTIVE


def test_upsert_changed_items_ignores_json_key_order_and_whole_floats(tmp_path):
    engine = _country_db(tmp_path)
    score = {
        "vendor_id": "aws",
        "server_id": "a1.2xlarge",
        "benchmark_id": "bw_mem",
        "config": {"operation": "rd", "size": 1},
        "environment": {"a": 1, "b": 2},
        "score": 2,
        "status": Status.ACTIVE,
    }
    reordered = {
        **score,
        "config": {"size": 1.0, "operation": "rd"},
        "environment": {"b": 2.0, "a": 1},
        "score": 2.0,
    }
    with Session(engine) as session:
        upsert_changed_items(BenchmarkScore, [score], session=session)
        session.commit()
        stats = upsert_changed_items(BenchmarkScore, [reordered], session=session)
        assert stats == {"new": 0, "changed": 0, "unchanged": 1, "deactivated": 0}


def test_upsert_changed_items_keeps_provided_observed_at(tmp_path):
    engine = _country_db(tmp_path)
    provided = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    with Session(engine) as session:
        upsert_changed_items(Country, [dict(US)], session=session)
        session.commit()
        upsert_changed_items(
            Country,
            [{**US, "continent": "Americas", "observed_at": provided}],
            session=session,
        )
        session.commit()
        row = _rows(session, Country)['{"country_id": "US"}']
        assert row.observed_at.replace(tzinfo=UTC) == provided


def test_insert_items_overwrites_without_comparing(tmp_path):
    engine = _country_db(tmp_path)
    with Session(engine) as session:
        insert_items(Country, [dict(US)], session=session)
        session.commit()
        first = _rows(session, Country)['{"country_id": "US"}'].observed_at
        insert_items(Country, [dict(US)], session=session)
        session.commit()
        assert _rows(session, Country)['{"country_id": "US"}'].observed_at != first


def test_merge_changed_item_updates_observed_at_only_on_change(tmp_path):
    from sqlalchemy import event

    from sc_crawler.cli import supported_vendors

    engine = _country_db(tmp_path)
    vendor = next(v for v in supported_vendors if v.vendor_id == "aws")
    with Session(engine) as session:
        merge_changed_item(session, vendor.model_copy())
        session.commit()
        first = session.get(Vendor, "aws").observed_at

    statements = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    with Session(engine) as session:
        merge_changed_item(session, vendor.model_copy())
        session.commit()
        assert session.get(Vendor, "aws").observed_at == first
    assert not [s for s in statements if s.lstrip().upper().startswith("UPDATE")]

    with Session(engine) as session:
        merge_changed_item(session, vendor.model_copy(update={"name": "Renamed"}))
        session.commit()
        row = session.get(Vendor, "aws")
        assert row.name == "Renamed"
        assert row.observed_at != first
