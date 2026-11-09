from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from sc_crawler.table_fields import Status, StorageType
from sc_crawler.vendors import _aws
from sc_crawler.vendors._aws import (
    _get_network_speed_gbps,
    _get_storage_of_instance_type,
    _get_storages_of_instance_type,
)


def _network(performance, *cards):
    return {
        "NetworkInfo": {
            "NetworkPerformance": performance,
            "NetworkCards": [
                {"BaselineBandwidthInGbps": baseline, "PeakBandwidthInGbps": peak}
                for baseline, peak in cards
            ],
        }
    }


def test_aws_network_speed_single_card():
    assert _get_network_speed_gbps(_network("Up to 30 Gigabit", (6.25, 30.0))) == (
        6.25,
        30.0,
    )


def test_aws_network_speed_sums_cards():
    # c8gb.48xlarge
    assert _get_network_speed_gbps(
        _network("400 Gigabit", (200.0, 200.0), (200.0, 200.0))
    ) == (400.0, 400.0)
    # p4d.24xlarge
    assert _get_network_speed_gbps(
        _network("4x 100 Gigabit", *[(100.0, 100.0)] * 4)
    ) == (400.0, 400.0)


def test_aws_network_speed_capped_by_instance_total():
    # c6in.32xlarge reports the instance total on each card
    assert _get_network_speed_gbps(
        _network("200 Gigabit", (200.0, 200.0), (200.0, 200.0))
    ) == (200.0, 200.0)


def test_aws_network_speed_peak_is_instance_total():
    # p6-b200.48xlarge cards add up to less than the instance total
    assert _get_network_speed_gbps(_network("3200 Gigabit", *[(200.0, 200.0)] * 8)) == (
        1600.0,
        3200.0,
    )


def _storage(nvme_support, disk_type="ssd"):
    return {
        "InstanceStorageInfo": {
            "TotalSizeInGB": 32,
            "NvmeSupport": nvme_support,
            "Disks": [{"SizeInGB": 16, "Count": 2, "Type": disk_type}],
        }
    }


def test_aws_storage_type_nvme_support():
    assert _get_storage_of_instance_type(_storage("required")) == (32, "nvme ssd")
    assert _get_storage_of_instance_type(_storage("supported")) == (32, "nvme ssd")
    # c3/i2/m3/r3, x1/x1e
    assert _get_storage_of_instance_type(_storage("unsupported")) == (32, "ssd")
    assert _get_storage_of_instance_type(_storage("unsupported", "hdd")) == (32, "hdd")
    assert [
        disk.storage_type
        for disk in _get_storages_of_instance_type(_storage("unsupported"))
    ] == [StorageType.SSD, StorageType.SSD]


def test_aws_reconcile_server_status(monkeypatch):
    def _product(instance_type, reserved):
        terms = {"OnDemand": {"x": {}}}
        if reserved:
            terms["Reserved"] = {"y": {}}
        return {
            "product": {"attributes": {"instanceType": instance_type}},
            "terms": terms,
        }

    monkeypatch.setattr(
        _aws,
        "_collect_regions_servers",
        lambda vendor: {
            "us-east-1": {"m5.large": ["use1-az1"], "c8a.large": ["use1-az1"]}
        },
    )
    monkeypatch.setattr(
        _aws,
        "_get_server_products",
        lambda: [
            _product("m5.large", True),
            _product("c8a.large", False),  # new types lack Reserved terms too
            _product("g4ad.xlarge", False),
            _product("p3.2xlarge", False),
            _product("dl1.24xlarge", True),
        ],
    )
    servers = {
        server_id: SimpleNamespace(server_id=server_id, accelerator_count=0)
        for server_id in (
            "m5.large",
            "c8a.large",
            "g4ad.xlarge",
            "p3.2xlarge",
            "dl1.24xlarge",
            "u-6tb1.metal",
            "t3.spotonly",
        )
    }
    _aws._reconcile_server_status(
        SimpleNamespace(servers=list(servers.values())), {"t3.spotonly"}
    )
    assert {k: v.status for k, v in servers.items()} == {
        "m5.large": Status.ACTIVE,
        "c8a.large": Status.ACTIVE,
        "g4ad.xlarge": Status.RETIRED,
        "p3.2xlarge": Status.RETIRED,
        "dl1.24xlarge": Status.INACTIVE,
        "u-6tb1.metal": Status.INACTIVE,
        "t3.spotonly": Status.ACTIVE,
    }


def test_aws_spot_prices_inactive_for_servers_no_longer_available(monkeypatch):
    now = datetime.now(UTC)

    def _spot(instance_type, timestamp):
        return {
            "AvailabilityZone": "us-east-1a",
            "InstanceType": instance_type,
            "SpotPrice": "0.1",
            "Timestamp": timestamp,
        }

    monkeypatch.setattr(
        _aws,
        "_describe_spot_price_history",
        lambda region: [
            _spot("m5.large", now),
            _spot("t3.spotonly", now),
            # the last known price is returned even if it is months old
            _spot("g4ad.xlarge", now - timedelta(days=35)),
        ],
    )
    monkeypatch.setattr(
        _aws,
        "_collect_regions_servers",
        lambda vendor: {"us-east-1": {"m5.large": ["use1-az1"]}},
    )
    monkeypatch.setattr(
        _aws,
        "_get_server_products",
        lambda: [
            {
                "product": {"attributes": {"instanceType": "g4ad.xlarge"}},
                "terms": {"OnDemand": {"x": {}}},
            }
        ],
    )
    region = SimpleNamespace(region_id="us-east-1", status="active")
    vendor = MagicMock(
        vendor_id="aws",
        regions=[region],
        zones=[SimpleNamespace(name="us-east-1a", zone_id="use1-az1", region=region)],
        servers=[
            SimpleNamespace(server_id=server_id, accelerator_count=0)
            for server_id in ("m5.large", "t3.spotonly", "g4ad.xlarge")
        ],
    )
    prices = _aws.inventory_server_prices_spot(vendor)
    assert {row["server_id"]: row["status"] for row in prices} == {
        "m5.large": Status.ACTIVE,
        "t3.spotonly": Status.ACTIVE,
        "g4ad.xlarge": Status.INACTIVE,
    }
