from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sc_crawler.table_fields import Status
from sc_crawler.vendors._hcloud import _hcloud_location_status, _hcloud_server_status

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
    assert (
        _hcloud_server_status(
            SimpleNamespace(locations=[_location(available=False)]),
            now=_NOW,
        )
        == Status.INACTIVE
    )


def test_hcloud_server_status_without_locations_is_inactive():
    assert (
        _hcloud_server_status(SimpleNamespace(locations=None), now=_NOW)
        == Status.INACTIVE
    )
    assert (
        _hcloud_server_status(SimpleNamespace(locations=[]), now=_NOW)
        == Status.INACTIVE
    )
