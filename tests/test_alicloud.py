from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from cachier import get_global_params, set_global_params
from Tea.exceptions import TeaException

from sc_crawler.inspector import _standardize_gpu_count
from sc_crawler.table_fields import (
    AcceleratorType,
    Disk,
    PriceUnit,
    Status,
    StorageType,
)
from sc_crawler.utils import _GIB_TO_GB
from sc_crawler.vendor_helpers import server_status_from_availability_categories
from sc_crawler.vendors._alicloud import (
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_LIFECYCLE,
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_STATUS,
    _DISK_CATEGORY_TO_STORAGE_IDS,
    _accelerator_type,
    _compatible_storage_ids,
    _get_instance_type_disk_categories,
    _gpu_manufacturer_of_family,
    _gpu_memory_by_spec,
    _instance_category,
    _local_disk_speed,
    _local_disks,
    _warn_unknown_category,
    _warn_unknown_disk_category,
    _warn_unknown_local_disk_speed,
    inventory_servers,
    inventory_storage_prices,
    inventory_storages,
)


@pytest.fixture(autouse=True)
def no_disk_cache():
    """Never read or write the cachier disk cache in tests."""
    enabled = get_global_params().caching_enabled
    set_global_params(caching_enabled=False)
    yield
    set_global_params(caching_enabled=enabled)


def test_standardize_gpu_count_from_alicloud_gpuspec():
    """AliCloud encodes fractional vGPUs in GPUSpec, e.g. "NVIDIA P4*1/4"."""
    assert _standardize_gpu_count("NVIDIA P4*1/4", 1) == 0.25
    assert _standardize_gpu_count("NVIDIA T4/8", 1) == 0.125
    assert _standardize_gpu_count("NVIDIA A10*1", 1) == 1
    # whole counts are returned as-is, so descriptions stay "8xV100"
    assert _standardize_gpu_count("NVIDIA V100", 8) == 8
    assert isinstance(_standardize_gpu_count("NVIDIA V100", 8), int)
    assert _standardize_gpu_count("", 0) == 0


def _instance_type(type_id, family, category):
    return {
        "InstanceTypeId": type_id,
        "InstanceTypeFamily": family,
        "InstanceCategory": category,
        "CpuArchitecture": "X86",
        "CpuCoreCount": 2,
        "MemorySize": 8.0,
        "LocalStorageCategory": "",
        "GPUSpec": "",
        "GPUAmount": 0,
        "PhysicalProcessorModel": "",
        "InstanceFamilyLevel": "EnterpriseLevel",
    }


def test_alicloud_instance_category_is_family_and_warned_once():
    _warn_unknown_category.cache_clear()
    with patch("sc_crawler.vendors._alicloud.logger") as logger:
        assert (
            _instance_category(
                _instance_type("ecs.g7.large", "ecs.g7", "General-purpose")
            )
            == "General Purpose"
        )
        # spelling unified with the other vendors: no hyphens
        assert (
            _instance_category(
                _instance_type("ecs.c7.large", "ecs.c7", "Compute-optimized")
            )
            == "Compute Optimized"
        )
        assert (
            _instance_category(
                _instance_type("ecs.hfc6.large", "ecs.hfc6", "High Performance Compute")
            )
            == "High Performance Computing"
        )
        # retired family without category in the API: category of the docs
        assert (
            _instance_category(_instance_type("ecs.n1.small", "ecs.n1", "")) == "Shared"
        )
        missing = _instance_type("ecs.new.large", "ecs.new", "")
        assert _instance_category(missing) is None
        assert _instance_category(missing) is None
    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert len(warnings) == 1
    assert "ecs.new.large" in warnings[0]


def test_alicloud_inventory_servers_sets_family_and_series():
    instance_types = [
        _instance_type("ecs.g7.large", "ecs.g7", "General-purpose"),
        _instance_type("ecs.gn5-c4g1.xlarge", "ecs.gn5", "Compute-optimized with GPU"),
        _instance_type("ecs.hfg5.large", "ecs.hfg5", "General-purpose"),
        # docs entry of the instance type wins over its series
        _instance_type("ecs.s2.small", "ecs.s2", "General-purpose"),
        _instance_type("ecs.s2.large", "ecs.s2", "General-purpose"),
    ]
    with (
        patch(
            "sc_crawler.vendors._alicloud._get_instance_types",
            return_value=instance_types,
        ),
        patch(
            "sc_crawler.vendors._alicloud._get_region_availability_info",
            return_value={},
        ),
        patch(
            "sc_crawler.vendors._alicloud._get_instance_type_disk_categories",
            return_value={"ecs.g7.large": ["cloud_auto", "cloud_essd", "cloud_ssd"]},
        ),
    ):
        vendor = Mock(vendor_id="alicloud")
        rows = inventory_servers(vendor)
    by_id = {row["server_id"]: row for row in rows}
    assert by_id["ecs.g7.large"]["compatible_storage_ids"] == [
        "cloud_essd-pl0",
        "cloud_essd-pl1",
        "cloud_essd-pl2",
        "cloud_essd-pl3",
        "cloud_auto",
        "cloud_ssd",
    ]
    # not in the API answer: the docs list of its series
    assert by_id["ecs.gn5-c4g1.xlarge"]["compatible_storage_ids"] == [
        "cloud_ssd",
        "cloud_efficiency",
    ]
    assert by_id["ecs.s2.small"]["compatible_storage_ids"] == ["cloud"]
    # neither API nor docs: unknown (None) and one summary warning
    assert by_id["ecs.hfg5.large"]["compatible_storage_ids"] is None
    assert by_id["ecs.s2.large"]["compatible_storage_ids"] is None
    vendor.log.assert_called_once()
    assert "2 instance types" in vendor.log.call_args.args[0]
    assert "ecs.hfg5.large" in vendor.log.call_args.args[0]
    assert by_id["ecs.g7.large"]["family"] == "General Purpose"
    assert by_id["ecs.g7.large"]["series"] == "ecs.g7"
    assert by_id["ecs.gn5-c4g1.xlarge"]["family"] == "Compute Optimized with GPU"
    assert by_id["ecs.gn5-c4g1.xlarge"]["series"] == "ecs.gn5"
    # description still shows the series
    assert by_id["ecs.g7.large"]["description"].startswith("ecs.g7 family (")


def _instance_type_with_disks(type_id, family, disks, gib):
    return {
        "InstanceTypeId": type_id,
        "InstanceTypeFamily": family,
        "LocalStorageAmount": disks,
        "LocalStorageCapacity": gib,
    }


@pytest.mark.parametrize(
    "instance_type,expected",
    [
        # no local disk
        (
            _instance_type_with_disks("ecs.g7.large", "ecs.g7", 0, 0),
            (None, None, None, None),
        ),
        # per instance type table: read IOPS only, GB/s -> MB/s
        (
            _instance_type_with_disks("ecs.i4.large", "ecs.i4", 1, 447),
            (112_500, None, 750, 375),
        ),
        # shared column of two families
        (
            _instance_type_with_disks("ecs.i4r.4xlarge", "ecs.i4r", 1, 894),
            (250_000, None, 1_500, 1_000),
        ),
        (
            _instance_type_with_disks("ecs.i2gne.2xlarge", "ecs.i2gne", 1, 894),
            (250_000, None, 1_500, 1_000),
        ),
        # i2 with more disks: throughput per disk x count, IOPS not published
        (
            _instance_type_with_disks("ecs.i2.8xlarge", "ecs.i2", 4, 1788),
            (None, None, 8_000, 4_000),
        ),
        # i2 largest size: published overall IOPS (not 8 x 300k)
        (
            _instance_type_with_disks("ecs.i2.16xlarge", "ecs.i2", 8, 1788),
            (1_500_000, None, 16_000, 8_000),
        ),
        # i1 formula by capacity, x 2 disks, rounded
        (
            _instance_type_with_disks("ecs.i1.xlarge", "ecs.i1", 2, 104),
            (34_320, 34_320, 291, 177),
        ),
        # i1 caps: same as the published overall speed of the largest size
        (
            _instance_type_with_disks("ecs.i1.14xlarge", "ecs.i1", 2, 1456),
            (480_000, 480_000, 4_000, 2_400),
        ),
        # HDD: single throughput figure per disk, stored as read
        (
            _instance_type_with_disks("ecs.d1.14xlarge", "ecs.d1", 28, 5500),
            (None, None, 5_320, None),
        ),
        (
            _instance_type_with_disks("ecs.d3s.16xlarge", "ecs.d3s", 32, 11100),
            (None, None, 8_320, None),
        ),
        # per disk figure also covers variants of the family
        (
            _instance_type_with_disks("ecs.d1-c14d3.14xlarge", "ecs.d1", 12, 5500),
            (None, None, 2_280, None),
        ),
    ],
)
def test_alicloud_local_disk_speed(instance_type, expected):
    assert _local_disk_speed(instance_type) == expected


@pytest.mark.parametrize(
    "instance_type",
    [
        # same API family as ecs.i2, but other disks and not in the docs
        _instance_type_with_disks("ecs.i2d.21xlarge", "ecs.i2", 4, 3570),
        # same API family as ecs.i5e, but not in the docs
        _instance_type_with_disks("ecs.i5e-grds-4t.2xlarge", "ecs.i5e", 1, 3576),
        # larger than the largest listed size
        _instance_type_with_disks("ecs.d3c.28xlarge", "ecs.d3c", 8, 12800),
        # no figures in the docs at all
        _instance_type_with_disks("ecs.gn5-c4g1.xlarge", "ecs.gn5", 1, 440),
        # i1 formula without a disk capacity: empty, not 0
        _instance_type_with_disks("ecs.i1.xlarge", "ecs.i1", 2, 0),
    ],
)
def test_alicloud_local_disk_speed_unknown_is_empty_and_warned_once(instance_type):
    _warn_unknown_local_disk_speed.cache_clear()
    with patch("sc_crawler.vendors._alicloud.logger") as logger:
        assert _local_disk_speed(instance_type) == (None, None, None, None)
        assert _local_disk_speed(instance_type) == (None, None, None, None)
    warnings = [call.args[0] for call in logger.warning.call_args_list]
    assert len(warnings) == 1
    assert instance_type["InstanceTypeId"] in warnings[0]


def test_alicloud_inventory_servers_bundled_storage_speed():
    with_disk = {
        **_instance_type("ecs.i4.large", "ecs.i4", "Local SSD"),
        "LocalStorageCategory": "local_ssd_pro",
        "LocalStorageAmount": 1,
        "LocalStorageCapacity": 447,
    }
    # disks with an unknown (empty) category: no disk entries, so no speed
    unknown_category = {
        **_instance_type("ecs.d1.2xlarge", "ecs.d1", "Big Data"),
        "LocalStorageAmount": 4,
        "LocalStorageCapacity": 5500,
    }
    instance_types = [
        with_disk,
        _instance_type("ecs.g7.large", "ecs.g7", "General-purpose"),
        unknown_category,
    ]
    with (
        patch(
            "sc_crawler.vendors._alicloud._get_instance_types",
            return_value=instance_types,
        ),
        patch(
            "sc_crawler.vendors._alicloud._get_region_availability_info",
            return_value={},
        ),
        patch(
            "sc_crawler.vendors._alicloud._get_instance_type_disk_categories",
            return_value={},
        ),
    ):
        rows = inventory_servers(Mock(vendor_id="alicloud"))
    speeds = {
        row["server_id"]: (
            row["storage_read_iops_max"],
            row["storage_write_iops_max"],
            row["storage_read_throughput_max"],
            row["storage_write_throughput_max"],
        )
        for row in rows
    }
    assert speeds == {
        "ecs.i4.large": (112_500, None, 750, 375),
        "ecs.g7.large": (None, None, None, None),
        "ecs.d1.2xlarge": (None, None, None, None),
    }
    storages = {row["server_id"]: row["storages"] for row in rows}
    assert storages["ecs.g7.large"] == []
    assert storages["ecs.d1.2xlarge"] == []
    assert storages["ecs.i4.large"] == [
        Disk(
            size=round(447 * 1024**3 / 1000**3),
            storage_type=StorageType.SSD,
            read_iops_max=112_500,
            read_throughput_max=750,
            write_throughput_max=375,
        )
    ]


@pytest.mark.parametrize(
    "amount,speed,expected",
    [
        # docs totals split evenly over the identical disks
        (
            4,
            (1_500_000, None, 16_000, 8_000),
            (375_000, None, 4_000, 2_000),
        ),
        # HDD: read throughput only
        (12, (None, None, 12 * 190, None), (None, None, 190, None)),
        # unknown speed: disks listed without speed
        (2, (None, None, None, None), (None, None, None, None)),
    ],
)
def test_alicloud_local_disks(amount, speed, expected):
    instance_type = {"LocalStorageAmount": amount, "LocalStorageCapacity": 1788}
    disks = _local_disks(instance_type, StorageType.SSD, speed)
    assert len(disks) == amount
    assert {
        (
            d.size,
            d.read_iops_max,
            d.write_iops_max,
            d.read_throughput_max,
            d.write_throughput_max,
        )
        for d in disks
    } == {(round(1788 * 1024**3 / 1000**3), *expected)}


@pytest.mark.parametrize(
    "family,amount,gib,speed,expected",
    [
        # documented per-disk speed, not the instance total / 8 (187,500 IOPS)
        (
            "ecs.i2",
            8,
            1788,
            (1_500_000, None, 16_000, 8_000),
            (300_000, None, 2_000, 1_000),
        ),
        # instance IOPS not published, per-disk IOPS is
        (
            "ecs.i2",
            4,
            1788,
            (None, None, 8_000, 4_000),
            (300_000, None, 2_000, 1_000),
        ),
        ("ecs.i2g", 1, 894, (150_000, None, 1_000, 500), (150_000, None, 1_000, 500)),
        # other disk size: falls back to the split
        ("ecs.i2", 2, 100, (None, None, 400, 200), (None, None, 200, 100)),
    ],
)
def test_alicloud_local_disks_i2_per_disk_speed(family, amount, gib, speed, expected):
    instance_type = {
        "InstanceTypeFamily": family,
        "LocalStorageAmount": amount,
        "LocalStorageCapacity": gib,
    }
    disks = _local_disks(instance_type, StorageType.SSD, speed)
    assert len(disks) == amount
    assert {
        (
            d.read_iops_max,
            d.write_iops_max,
            d.read_throughput_max,
            d.write_throughput_max,
        )
        for d in disks
    } == {expected}


def test_alicloud_local_disks_none():
    speed = (100, 100, 100, 100)
    # no local disk
    assert _local_disks({}, StorageType.SSD, speed) == []
    assert _local_disks({"LocalStorageAmount": 0}, StorageType.SSD, speed) == []
    # unknown category (empty LocalStorageCategory maps to None)
    assert _local_disks({"LocalStorageAmount": 2}, None, speed) == []


def _api_error(code):
    return TeaException({"code": code, "message": code})


def _availability_zone(zone_id, resource_type, values):
    """A zone of a DescribeAvailableResource response: (value, status) pairs."""
    return {
        "ZoneId": zone_id,
        "AvailableResources": {
            "AvailableResource": [
                {
                    "Type": resource_type,
                    "SupportedResources": {
                        "SupportedResource": [
                            {"Value": value, "StatusCategory": status}
                            for value, status in values
                        ]
                    },
                }
            ]
        },
    }


def test_alicloud_instance_type_disk_categories_parses_responses():
    availability = {
        "r1": [
            _availability_zone(
                "r1a",
                "InstanceType",
                [("ecs.g7.large", "WithStock"), ("ecs.n4.large", "WithoutStock")],
            ),
            # in stock in two zones: still one call for the region
            _availability_zone("r1b", "InstanceType", [("ecs.g7.large", "WithStock")]),
            # other resource types are ignored
            _availability_zone("r1c", "DataDisk", [("ecs.n4.large", "WithStock")]),
        ],
        "r2": [],
    }
    zones = [
        _availability_zone("a", "DataDisk", [("cloud_essd", "WithStock")]),
        _availability_zone(
            "b",
            "DataDisk",
            [("cloud_auto", "WithStock"), ("cloud_essd", "WithoutStock")],
        ),
        # system disks are not data disks
        _availability_zone("c", "SystemDisk", [("cloud_ssd", "WithStock")]),
        {},
    ]
    calls = []

    def describe(request, runtime):
        calls.append((request.region_id, request.instance_type))
        return SimpleNamespace(
            body=SimpleNamespace(
                to_map=lambda: {"AvailableZones": {"AvailableZone": zones}}
            )
        )

    client = SimpleNamespace(describe_available_resource_with_options=describe)
    with patch(
        "sc_crawler.vendors._alicloud._ecs_clients",
        return_value={"r1": client, "r2": client},
    ):
        result = _get_instance_type_disk_categories(
            Mock(vendor_id="alicloud"), availability
        )
    # union over zones; sold out n4 not asked
    assert result == {"ecs.g7.large": ["cloud_auto", "cloud_essd"]}
    assert calls == [("r1", "ecs.g7.large")]
    # nothing in stock: no calls, nothing known
    with patch("sc_crawler.vendors._alicloud._ecs_clients", return_value={}):
        assert _get_instance_type_disk_categories(Mock(), {}) == {}


def _data_disk_response(categories):
    zones = [
        _availability_zone("z", "DataDisk", [(c, "WithStock") for c in categories])
    ]
    return SimpleNamespace(
        body=SimpleNamespace(
            to_map=lambda: {"AvailableZones": {"AvailableZone": zones}}
        )
    )


def test_alicloud_instance_type_disk_categories_per_type_and_region():
    availability = {
        "r1": [
            _availability_zone(
                "r1a",
                "InstanceType",
                [
                    ("ecs.g7.large", "WithStock"),
                    ("ecs.n4.large", "WithStock"),
                    ("ecs.e.large", "WithStock"),
                    ("ecs.x.large", "WithStock"),
                    # to be retired, still in stock: asked as well
                    ("ecs.closing.large", "ClosedWithStock"),
                    ("ecs.old.large", "WithoutStock"),
                ],
            )
        ],
        "r2": [
            _availability_zone(
                "r2a",
                "InstanceType",
                [("ecs.g7.large", "WithStock"), ("ecs.e.large", "WithStock")],
            )
        ],
    }
    answers = {
        ("r1", "ecs.g7.large"): ["cloud_essd"],
        ("r2", "ecs.g7.large"): ["cloud", "cloud_essd"],
        ("r1", "ecs.n4.large"): ["cloud_efficiency", "cloud_ssd"],
        # failed in r1, answered in r2
        ("r1", "ecs.e.large"): _api_error("InternalError"),
        ("r2", "ecs.e.large"): ["cloud_essd_entry"],
        # empty answer: unknown, not "no storage"
        ("r1", "ecs.x.large"): [],
        ("r1", "ecs.closing.large"): ["cloud_essd"],
    }
    calls = []

    def client(region_id):
        def describe(request, runtime):
            calls.append((region_id, request.instance_type))
            assert request.destination_resource == "DataDisk"
            answer = answers[(region_id, request.instance_type)]
            if isinstance(answer, Exception):
                raise answer
            return _data_disk_response(answer)

        return SimpleNamespace(describe_available_resource_with_options=describe)

    vendor = Mock(vendor_id="alicloud")
    with patch(
        "sc_crawler.vendors._alicloud._ecs_clients",
        return_value={"r1": client("r1"), "r2": client("r2")},
    ):
        result = _get_instance_type_disk_categories(vendor, availability)
    assert result == {
        "ecs.g7.large": ["cloud", "cloud_essd"],
        "ecs.n4.large": ["cloud_efficiency", "cloud_ssd"],
        "ecs.e.large": ["cloud_essd_entry"],
        "ecs.closing.large": ["cloud_essd"],
    }
    # only where in stock: never for the sold out type
    assert sorted(calls) == sorted(answers)
    vendor.log.assert_called_once()
    assert "1 of 7" in vendor.log.call_args.args[0]


def test_alicloud_instance_type_disk_categories_raises_non_api_errors():
    availability = {
        "r1": [
            _availability_zone("r1a", "InstanceType", [("ecs.g7.large", "WithStock")])
        ]
    }

    def describe(request, runtime):
        raise AttributeError("changed SDK")

    with patch(
        "sc_crawler.vendors._alicloud._ecs_clients",
        return_value={
            "r1": SimpleNamespace(describe_available_resource_with_options=describe)
        },
    ):
        with pytest.raises(AttributeError):
            _get_instance_type_disk_categories(Mock(vendor_id="alicloud"), availability)


def test_alicloud_instance_type_disk_categories_retries_throttling():
    availability = {
        "r1": [
            _availability_zone("r1a", "InstanceType", [("ecs.g7.large", "WithStock")])
        ]
    }
    responses = [_api_error("Throttling.User"), _data_disk_response(["cloud_essd"])]

    def describe(request, runtime):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    vendor = Mock(vendor_id="alicloud")
    with (
        patch(
            "sc_crawler.vendors._alicloud._ecs_clients",
            return_value={
                "r1": SimpleNamespace(describe_available_resource_with_options=describe)
            },
        ),
        patch("sc_crawler.vendors._alicloud.sleep") as sleep,
    ):
        result = _get_instance_type_disk_categories(vendor, availability)
    assert result == {"ecs.g7.large": ["cloud_essd"]}
    sleep.assert_called_once()
    vendor.log.assert_not_called()


def _price_client(prices):
    """DescribePrice client returning hourly prices of 100 GB disks, by category."""

    def describe(request, runtime):
        assert request.resource_type == "disk"
        assert request.price_unit == "Hour"
        disk = request.data_disk[0]
        answer = prices[(request.region_id, disk.category)]
        if isinstance(answer, Exception):
            raise answer
        price = SimpleNamespace(original_price=answer * disk.size / 100, currency="USD")
        return SimpleNamespace(
            body=SimpleNamespace(price_info=SimpleNamespace(price=price))
        )

    return SimpleNamespace(describe_price_with_options=describe)


def _storage_prices(clients):
    """inventory_storage_prices with DescribePrice clients and no SKU prices."""
    vendor = Mock(vendor_id="alicloud")
    with (
        patch("sc_crawler.vendors._alicloud._get_storage_sku_prices", return_value=[]),
        patch("sc_crawler.vendors._alicloud._ecs_clients", return_value=clients),
    ):
        return vendor, inventory_storage_prices(vendor)


def test_alicloud_describe_price_storage_prices():
    prices = {
        ("r1", "cloud_auto"): 0.02512,
        ("r1", "cloud_essd_entry"): 0.01063,
        # not sold in the region: skipped, no warning
        ("r2", "cloud_auto"): _api_error("PriceNotFound"),
        ("r2", "cloud_essd_entry"): 0.01,
    }
    client = _price_client(prices)
    with patch("sc_crawler.vendors._alicloud.logger") as logger:
        vendor, items = _storage_prices({"r1": client, "r2": client})
    logger.warning.assert_not_called()
    by_key = {(i["region_id"], i["storage_id"]): i for i in items}
    assert set(by_key) == {
        ("r1", "cloud_auto"),
        ("r1", "cloud_essd_entry"),
        ("r2", "cloud_essd_entry"),
    }
    # 0.02512 USD per 100 GiB and hour, 730 hours a month, per GB
    assert by_key[("r1", "cloud_auto")]["price"] == pytest.approx(0.183376 / _GIB_TO_GB)
    assert by_key[("r1", "cloud_essd_entry")]["price"] == pytest.approx(
        0.077599 / _GIB_TO_GB
    )
    assert by_key[("r1", "cloud_auto")]["unit"] == PriceUnit.GB_MONTH
    assert by_key[("r1", "cloud_auto")]["currency"] == "USD"
    vendor.log.assert_called_once()
    assert "cloud_auto in r2" in vendor.log.call_args.args[0]


def test_alicloud_describe_price_errors_retry_and_empty_answer():
    answers = {
        # throttled once, then an answer without price
        "cloud_auto": [
            _api_error("Throttling.User"),
            SimpleNamespace(body=SimpleNamespace(price_info=None)),
        ],
        # other API error
        "cloud_essd_entry": [_api_error("InternalError")],
    }

    def describe(request, runtime):
        response = answers[request.data_disk[0].category].pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    client = SimpleNamespace(describe_price_with_options=describe)
    with (
        patch("sc_crawler.vendors._alicloud.sleep") as sleep,
        patch("sc_crawler.vendors._alicloud.logger") as logger,
    ):
        _, items = _storage_prices({"r1": client})
    assert items == []
    sleep.assert_called_once()
    # empty answer and other API error: warned
    assert logger.warning.call_count == 2


def test_alicloud_compatible_storage_ids():
    assert _compatible_storage_ids(["cloud_efficiency", "ephemeral_ssd"]) == [
        "cloud_efficiency"
    ]
    assert _compatible_storage_ids(["ephemeral_ssd"]) == []
    # temporary and undocumented categories are left out without warning, unknown
    # ones with a warning once
    _warn_unknown_disk_category.cache_clear()
    with patch("sc_crawler.vendors._alicloud.logger") as logger:
        assert _compatible_storage_ids(["cloud_new", "cloud_new"]) == []
        assert _compatible_storage_ids(["cloud_new"]) == []
    logger.warning.assert_called_once()
    assert "cloud_new" in logger.warning.call_args.args[0]
    assert _compatible_storage_ids(
        [
            "cloud_auto",
            "cloud_essd_entry",
            "elastic_ephemeral_disk_standard",
            "cloud_xssd",
        ]
    ) == ["cloud_auto", "cloud_essd_entry"]
    assert _compatible_storage_ids([]) == []


def test_alicloud_disk_category_mapping_matches_storage_ids():
    storage_ids = {s["storage_id"] for s in inventory_storages(Mock(vendor_id="a"))}
    mapped = {i for ids in _DISK_CATEGORY_TO_STORAGE_IDS.values() for i in ids}
    assert mapped == storage_ids


def test_alicloud_autopl_and_entry_storages():
    by_id = {s["storage_id"]: s for s in inventory_storages(Mock(vendor_id="a"))}
    auto, entry = by_id["cloud_auto"], by_id["cloud_essd_entry"]
    # GiB in the docs, GB here
    assert (auto["min_size"], auto["max_size"]) == (1, 70369)
    assert (entry["min_size"], entry["max_size"]) == (11, 35184)
    assert auto["storage_type"].value == "ssd"
    # the price covers the baseline only
    assert auto["max_iops"] == 50000
    assert "not included in the price" in auto["description"]


def test_alicloud_essd_descriptions_name_the_api_values():
    by_id = {s["storage_id"]: s for s in inventory_storages(Mock(vendor_id="a"))}
    for pl in range(4):
        description = by_id[f"cloud_essd-pl{pl}"]["description"]
        assert f"DiskCategory cloud_essd, PerformanceLevel PL{pl}" in description
    # other categories are the API value as is
    assert "PerformanceLevel" not in by_id["cloud_ssd"]["description"]


def test_alicloud_gpu_memory_by_spec_only_when_unambiguous():
    instance_types = [
        {"InstanceTypeId": "ecs.gn7s-c8g1.2xlarge", "GPUSpec": "NVIDIA A30"},
        {"InstanceTypeId": "x", "GPUSpec": "NVIDIA A30", "GPUMemorySize": 24},
        {"InstanceTypeId": "y", "GPUSpec": "NVIDIA V100", "GPUMemorySize": 16},
        {"InstanceTypeId": "z", "GPUSpec": "NVIDIA V100", "GPUMemorySize": 32.0},
        {"InstanceTypeId": "ecs.gn4.8xlarge", "GPUSpec": "NVIDIA M40"},
        {"InstanceTypeId": "ecs.g7nex.large", "GPUSpec": ""},
    ]
    assert _gpu_memory_by_spec(instance_types) == {"NVIDIA A30": 24.0}


def test_alicloud_server_lifecycle_keeps_out_of_stock_types_active():
    lifecycle = _ALICLOUD_STATUS_CATEGORY_TO_SERVER_LIFECYCLE
    assert (
        server_status_from_availability_categories({"WithoutStock"}, lifecycle)
        == Status.ACTIVE
    )
    assert (
        server_status_from_availability_categories({"ClosedWithoutStock"}, lifecycle)
        == Status.RETIRED
    )
    assert server_status_from_availability_categories(set(), lifecycle) == (
        Status.INACTIVE
    )
    # per-zone prices still follow the stock
    assert not _ALICLOUD_STATUS_CATEGORY_TO_SERVER_STATUS["WithoutStock"].is_orderable


@pytest.mark.parametrize(
    "gpu_model,gpu_count,expected",
    [
        ("T4", 1, AcceleratorType.GPU),
        (None, 1, AcceleratorType.GPU),
        ("VG1000", 1, AcceleratorType.GPU),
        ("T4", 0, None),
        ("VU9P", 1, AcceleratorType.FPGA),
        ("Arria 10 GX 1150", 1, AcceleratorType.FPGA),
        ("AGF027", 1, AcceleratorType.FPGA),
        ("T408", 12, AcceleratorType.VPU),
        ("ALINPU 800", 4, AcceleratorType.NPU),
        ("PPU 810", 1, AcceleratorType.NPU),
        ("A910E", 8, AcceleratorType.NPU),
        ("A910X", 8, AcceleratorType.NPU),
        ("A910Z", 8, AcceleratorType.NPU),
    ],
)
def test_accelerator_type(gpu_model, gpu_count, expected):
    """GPUSpec models map to their accelerator type, defaulting to GPU."""
    assert _accelerator_type(gpu_model, gpu_count) == expected


@pytest.mark.parametrize(
    "family,expected",
    [
        ("ecs.gn8v", "NVIDIA"),
        ("ecs.ebmgn7t", "NVIDIA"),
        ("ecs.ebmgp7", None),
        ("ecs.av8m", None),
        (None, None),
    ],
)
def test_gpu_manufacturer_of_family(family, expected):
    assert _gpu_manufacturer_of_family(family) == expected


def test_alicloud_inventory_storage_prices_per_gb():
    skus = [
        {
            "SkuFactorMap": {
                "datadisk_category": "cloud_essd",
                "datadisk_performance_level": "PL1",
                "vm_region_no": "r1",
            },
            "CskuPriceList": [
                {"Price": "0.0002", "PriceType": "hourPrice", "Currency": "USD"}
            ],
        }
    ]
    vendor = Mock(vendor_id="alicloud")
    with (
        patch(
            "sc_crawler.vendors._alicloud._get_storage_sku_prices", return_value=skus
        ),
        patch(
            "sc_crawler.vendors._alicloud.get_region_by_id",
            return_value=Mock(region_id="r1"),
        ),
        patch("sc_crawler.vendors._alicloud._ecs_clients", return_value={}),
    ):
        items = inventory_storage_prices(vendor)
    assert items[0]["storage_id"] == "cloud_essd-pl1"
    # per GiB and hour in the API, per GB and month here
    assert items[0]["price"] == pytest.approx(0.0002 * 730 / _GIB_TO_GB)
    assert len(items) == 1
