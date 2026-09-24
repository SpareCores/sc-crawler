from alembic import command
from sqlalchemy import update
from sqlmodel import Session, select

from sc_crawler.alembic_helpers import alembic_cfg
from sc_crawler.insert import (
    INACTIVE_CONTENT_FLIPS,
    ROW_CONTENT_HASHES,
    _dedupe_items,
    _primary_key_tuple,
    insert_items,
)
from sc_crawler.tables import Country
from sc_crawler.utils import create_sc_engine
from sc_crawler.table_bases import (
    BenchmarkScoreBase,
    DatabaseBase,
    DatabasePriceBase,
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


def test_insert_items_skips_rows_unchanged_except_observed_at(tmp_path):
    item = {"country_id": "US", "continent": "North America", "status": Status.ACTIVE}
    engine = _country_db(tmp_path)
    with Session(engine) as session:
        insert_items(Country, [item], session=session)
        session.commit()
        observed_at = session.exec(select(Country)).one().observed_at

    with Session(engine) as session:
        insert_items(Country, [dict(item)], session=session)
        session.commit()
        row = session.exec(select(Country)).one()
        assert row.continent == "North America"
        assert row.observed_at == observed_at

        insert_items(
            Country,
            [{**item, "continent": "Americas"}],
            session=session,
        )
        session.commit()
        session.expire_all()
        row = session.exec(select(Country)).one()
        assert row.continent == "Americas"
        assert row.observed_at != observed_at


def test_insert_items_restores_status_without_changing_observed_at(tmp_path):
    item = {"country_id": "US", "continent": "North America", "status": Status.ACTIVE}
    engine = _country_db(tmp_path)
    with Session(engine) as session:
        insert_items(Country, [item], session=session)
        session.commit()
        observed_at = session.exec(select(Country)).one().observed_at

        session.expire_all()
        session.info.pop(ROW_CONTENT_HASHES, None)
        session.info[ROW_CONTENT_HASHES] = {
            Country.get_table_name(): Country.hash(session)
        }
        session.info.setdefault(INACTIVE_CONTENT_FLIPS, set()).add(
            Country.get_table_name()
        )
        session.exec(
            update(Country).values(
                status=Status.INACTIVE, observed_at=Country.observed_at
            )
        )
        insert_items(Country, [dict(item)], session=session)
        session.commit()
        session.expire_all()
        row = session.exec(select(Country)).one()
        assert row.status == Status.ACTIVE
        assert row.observed_at == observed_at
        assert row.continent == "North America"
