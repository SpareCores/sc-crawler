from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from sc_crawler.table_fields import Status
from sc_crawler.vendors._hcloud import (
    _hcloud_location_status,
    _hcloud_server_status,
    _server_cpu,
    inventory_servers,
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
    assert (
        _hcloud_server_status(
            SimpleNamespace(locations=[_location(available=False)]),
            now=_NOW,
        )
        == Status.INACTIVE
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


def test_hcloud_inventory_servers_maps_compatible_storage_ids():
    server = SimpleNamespace(
        id=1,
        name="cx22",
        description="Test server",
        cores=2,
        cpu_type="shared",
        architecture="x86",
        memory=4,
        disk=40,
        prices=[{"included_traffic": 1024}],
        locations=[],
        category="Cost Optimized",
    )

    with (
        patch("sc_crawler.vendors._hcloud._get_server_types", return_value=[server]),
        patch(
            "sc_crawler.vendors._hcloud._server_cpu",
            return_value=("Intel", "Xeon", "Test"),
        ),
    ):
        rows = inventory_servers(SimpleNamespace(vendor_id="hcloud"))

    assert len(rows) == 1
    assert rows[0]["compatible_storage_ids"] == ["block"]
