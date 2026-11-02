from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sc_crawler.table_fields import Status
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
