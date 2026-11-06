from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlmodel import Session, SQLModel, create_engine

from sc_crawler import tables
from sc_crawler.table_fields import Status
from sc_crawler.vendors import hcloud
from sc_crawler.vendors._hcloud import (
    _hcloud_location_status,
    _hcloud_server_status,
    _retired_servers,
    _server_cpu,
)

_NOW = datetime(2026, 8, 17, tzinfo=UTC)


def _location(*, deprecation=None, available=True, name="fsn1"):
    return SimpleNamespace(
        location=SimpleNamespace(name=name),
        deprecation=deprecation,
        available=available,
    )


def test_hcloud_location_status():
    future = _NOW + timedelta(days=30)
    past = _NOW - timedelta(days=1)

    assert _hcloud_location_status(_location(), _NOW) == Status.ACTIVE
    assert (
        _hcloud_location_status(
            _location(deprecation=SimpleNamespace(unavailable_after=future)),
            _NOW,
        )
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert (
        _hcloud_location_status(
            _location(deprecation=SimpleNamespace(unavailable_after=past)),
            _NOW,
        )
        == Status.RETIRED
    )
    assert _hcloud_location_status(_location(available=False), _NOW) == Status.INACTIVE
    assert _hcloud_location_status(None, _NOW) == Status.INACTIVE


def test_hcloud_server_status_from_per_location_deprecation():
    future = _NOW + timedelta(days=30)
    past = _NOW - timedelta(days=1)

    assert (
        _hcloud_server_status(
            SimpleNamespace(locations=[_location()]),
            now=_NOW,
        )
        == Status.ACTIVE
    )
    assert (
        _hcloud_server_status(
            SimpleNamespace(
                locations=[
                    _location(deprecation=SimpleNamespace(unavailable_after=future))
                ],
            ),
            now=_NOW,
        )
        == Status.PLANNED_FOR_RETIREMENT
    )
    assert (
        _hcloud_server_status(
            SimpleNamespace(
                locations=[
                    _location(),
                    _location(
                        deprecation=SimpleNamespace(unavailable_after=future),
                        name="nbg1",
                    ),
                ],
            ),
            now=_NOW,
        )
        == Status.ACTIVE
    )
    assert (
        _hcloud_server_status(
            SimpleNamespace(
                locations=[
                    _location(),
                    _location(
                        deprecation=SimpleNamespace(unavailable_after=past),
                        name="nbg1",
                    ),
                ],
            ),
            now=_NOW,
        )
        == Status.ACTIVE
    )
    assert (
        _hcloud_server_status(
            SimpleNamespace(
                locations=[
                    _location(deprecation=SimpleNamespace(unavailable_after=past))
                ],
            ),
            now=_NOW,
        )
        == Status.RETIRED
    )
    # sold out everywhere is still offered
    assert (
        _hcloud_server_status(
            SimpleNamespace(locations=[_location(available=False)]),
            now=_NOW,
        )
        == Status.ACTIVE
    )
    # sold out beats retired elsewhere
    assert (
        _hcloud_server_status(
            SimpleNamespace(
                locations=[
                    _location(available=False),
                    _location(
                        deprecation=SimpleNamespace(unavailable_after=past),
                        name="nbg1",
                    ),
                ],
            ),
            now=_NOW,
        )
        == Status.ACTIVE
    )


def test_hcloud_server_cpu_marks_legacy_ccx_as_intel():
    assert _server_cpu(
        SimpleNamespace(name="ccx11", architecture="x86", category="general_purpose")
    ) == ("Intel", None, None)
    assert _server_cpu(
        SimpleNamespace(name="ccx13", architecture="x86", category="general_purpose")
    ) == ("AMD", None, None)


def test_hcloud_server_status_without_locations_is_inactive():
    assert (
        _hcloud_server_status(SimpleNamespace(locations=None), now=_NOW)
        == Status.INACTIVE
    )
    assert (
        _hcloud_server_status(SimpleNamespace(locations=[]), now=_NOW)
        == Status.INACTIVE
    )


def test_hcloud_retired_servers_are_known_ones_missing_from_the_api():
    def _server(server_id, status=Status.INACTIVE):
        return SimpleNamespace(
            server_id=server_id,
            model_dump=lambda exclude: {"server_id": server_id, "status": status},
        )

    vendor = SimpleNamespace(servers=[_server("1"), _server("2")])
    assert _retired_servers(vendor, [SimpleNamespace(id=1)]) == [
        {"server_id": "2", "status": Status.RETIRED}
    ]
    assert (
        _retired_servers(vendor, [SimpleNamespace(id=1), SimpleNamespace(id=2)]) == []
    )


def test_inventory_servers_loads_known_servers_after_retired_servers_lookup(
    monkeypatch,
):
    """Benchmarks and descriptions load for servers already in the database.

    On an empty database the new rows are only picked up by the next pull.
    """
    server = {
        "vendor_id": "hcloud",
        "server_id": "1",
        "name": "cx23",
        "api_reference": "cx23",
        "display_name": "cx23",
        "description": "cx23",
        "vcpus": 2,
        "cpu_allocation": "Shared",
        "cpu_architecture": "x86_64",
        "cpu_flags": [],
        "cpus": [],
        "memory_amount": 4096,
        "accelerator_count": 0,
        "accelerators": [],
        "storage_size": 40,
        "storages": [],
        "inbound_traffic": 0,
        "outbound_traffic": 0,
        "ipv4": 1,
        "status": Status.ACTIVE,
    }

    def inventory_servers(vendor):
        # the vendor method reads the relationship before the new rows are inserted
        return [server, *_retired_servers(vendor, [SimpleNamespace(id=1)])]

    benchmarked, described = [], []
    monkeypatch.setattr(tables, "inspector_data_path", lambda: None)
    monkeypatch.setattr(tables, "descriptions_data_path", lambda: None)
    monkeypatch.setattr(tables, "inspect_update_server_dict", lambda item: item)
    monkeypatch.setattr(
        tables,
        "inspect_server_benchmarks",
        lambda item: benchmarked.append(item.server_id) or [],
    )
    monkeypatch.setattr(
        tables,
        "ingest_server_description",
        lambda item: described.append(item.server_id),
    )

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        vendor = session.merge(hcloud)
        session.merge(tables.Server.model_validate(server))
        session.commit()
        vendor.session = session
        vendor.progress_tracker = MagicMock()
        vendor._methods = SimpleNamespace(inventory_servers=inventory_servers)
        vendor.inventory_servers()

    assert benchmarked == ["1"]
    assert described == ["1"]
