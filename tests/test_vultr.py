from unittest.mock import Mock, patch

from sc_crawler.table_fields import Status
from sc_crawler.vendors._vultr import inventory_servers


def _plan(plan_id, locations):
    return {
        "id": plan_id,
        "type": "vc2",
        "vcpu_count": 1,
        "ram": 1024,
        "disk": 25,
        "disk_count": 1,
        "bandwidth": 1024,
        "cpu_model": "",
        "locations": locations,
    }


def test_vultr_inventory_servers_status_from_locations():
    vendor = Mock(vendor_id="vultr")
    with (
        patch(
            "sc_crawler.vendors._vultr._get_plans",
            return_value=[
                _plan("vc2-1c-1gb", ["ewr"]),
                _plan("vc2-1c-0.5gb-free", ["ewr"]),
                _plan("vc2-24c-97gb", []),
            ],
        ),
        patch("sc_crawler.vendors._vultr._get_plans_metal", return_value=[]),
    ):
        rows = inventory_servers(vendor)
    by_id = {row["server_id"]: row for row in rows}
    assert by_id["vc2-1c-1gb"]["status"] == Status.ACTIVE
    assert by_id["vc2-1c-0.5gb-free"]["status"] == Status.INACTIVE
    assert by_id["vc2-24c-97gb"]["status"] == Status.INACTIVE
