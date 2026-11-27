from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from cachier import get_global_params, set_global_params
from Tea.exceptions import TeaException

from sc_crawler.inspector import _standardize_gpu_count
from sc_crawler.table_fields import AcceleratorType, Status
from sc_crawler.utils import _GIB_TO_GB
from sc_crawler.vendor_helpers import server_status_from_availability_categories
from sc_crawler.vendors._alicloud import (
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_LIFECYCLE,
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_STATUS,
    _DISK_CATEGORY_TO_STORAGE_IDS,
    _accelerator_type,
    _compatible_storage_ids,
    _docs_disk_categories,
    _get_describe_price_storage_prices,
    _get_disk_price,
    _get_instance_type_disk_categories,
    _gpu_manufacturer_of_family,
    _gpu_memory_by_spec,
    _instance_category,
    _parse_data_disk_categories,
    _warn_unknown_category,
    _warn_unknown_disk_category,
    _with_stock_regions,
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
    # neither API nor docs: unknown (None) and one summary warning
    assert by_id["ecs.hfg5.large"]["compatible_storage_ids"] is None
    vendor.log.assert_called_once()
    assert "1 instance types" in vendor.log.call_args.args[0]
    assert "ecs.hfg5.large" in vendor.log.call_args.args[0]
    assert by_id["ecs.g7.large"]["family"] == "General Purpose"
    assert by_id["ecs.g7.large"]["series"] == "ecs.g7"
    assert by_id["ecs.gn5-c4g1.xlarge"]["family"] == "Compute Optimized with GPU"
    assert by_id["ecs.gn5-c4g1.xlarge"]["series"] == "ecs.gn5"
    # description still shows the series
    assert by_id["ecs.g7.large"]["description"].startswith("ecs.g7 family (")


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


def test_alicloud_with_stock_regions():
    info = {
        "r1": [
            _availability_zone(
                "r1a",
                "InstanceType",
                [("ecs.g7.large", "WithStock"), ("ecs.n4.large", "WithoutStock")],
            ),
            _availability_zone("r1b", "InstanceType", [("ecs.g7.large", "WithStock")]),
        ],
        "r2": [
            _availability_zone("r2a", "InstanceType", [("ecs.g7.large", "WithStock")]),
            # other resource types are ignored
            _availability_zone("r2b", "DataDisk", [("ecs.n4.large", "WithStock")]),
        ],
        "r3": [],
    }
    # sold out everywhere (n4): not listed
    assert _with_stock_regions(info) == {"ecs.g7.large": ["r1", "r2"]}
    assert _with_stock_regions({}) == {}


def test_alicloud_parse_data_disk_categories_merges_zones():
    zones = [
        _availability_zone("a", "DataDisk", [("cloud_essd", "WithStock")]),
        _availability_zone(
            "b",
            "DataDisk",
            [("cloud_auto", "WithStock"), ("cloud_essd", "WithoutStock")],
        ),
        _availability_zone("c", "SystemDisk", [("cloud_ssd", "WithStock")]),
        {},
    ]
    assert _parse_data_disk_categories(zones) == ["cloud_auto", "cloud_essd"]
    assert _parse_data_disk_categories([]) == []


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


def test_alicloud_docs_disk_categories():
    assert _docs_disk_categories("ecs.gn5-c4g1.2xlarge", "ecs.gn5") == [
        "cloud_efficiency",
        "cloud_ssd",
    ]
    # the instance type wins over its series
    assert _docs_disk_categories("ecs.s2.small", "ecs.s2") == ["cloud"]
    assert _docs_disk_categories("ecs.s2.large", "ecs.s2") is None
    assert _docs_disk_categories("ecs.hfg5.large", "ecs.hfg5") is None
    assert _docs_disk_categories("ecs.x", None) is None


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


def test_alicloud_disk_price_per_gb_month():
    client = _price_client({("r1", "cloud_auto"): 0.02512})
    price = _get_disk_price(client, "r1", "cloud_auto")
    # 0.02512 USD per 100 GiB and hour, 730 hours a month, per GB
    assert price["price"] == pytest.approx(0.183376 / _GIB_TO_GB)
    assert price["currency"] == "USD"
    with patch("sc_crawler.vendors._alicloud.logger") as logger:
        # not sold in the region: no warning
        client = _price_client({("r1", "cloud_auto"): _api_error("PriceNotFound")})
        assert _get_disk_price(client, "r1", "cloud_auto") is None
        logger.warning.assert_not_called()
        # other API errors: warned
        client = _price_client({("r1", "cloud_auto"): _api_error("InternalError")})
        assert _get_disk_price(client, "r1", "cloud_auto") is None
        logger.warning.assert_called_once()


def test_alicloud_disk_price_retries_throttling_and_handles_empty_answer():
    responses = [
        _api_error("Throttling.User"),
        SimpleNamespace(body=SimpleNamespace(price_info=None)),
    ]

    def describe(request, runtime):
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    client = SimpleNamespace(describe_price_with_options=describe)
    with (
        patch("sc_crawler.vendors._alicloud.sleep") as sleep,
        patch("sc_crawler.vendors._alicloud.logger") as logger,
    ):
        assert _get_disk_price(client, "r1", "cloud_auto") is None
    sleep.assert_called_once()
    logger.warning.assert_called_once()


def test_alicloud_describe_price_storage_prices_skip_unpriced_regions():
    prices = {
        ("r1", "cloud_auto"): 0.02512,
        ("r1", "cloud_essd_entry"): 0.01063,
        ("r2", "cloud_auto"): _api_error("PriceNotFound"),
        ("r2", "cloud_essd_entry"): 0.01,
    }
    vendor = Mock(vendor_id="alicloud")
    with patch(
        "sc_crawler.vendors._alicloud._ecs_clients",
        return_value={"r1": _price_client(prices), "r2": _price_client(prices)},
    ):
        items = _get_describe_price_storage_prices(vendor)
    by_key = {(i["region_id"], i["storage_id"]): i for i in items}
    assert set(by_key) == {
        ("r1", "cloud_auto"),
        ("r1", "cloud_essd_entry"),
        ("r2", "cloud_essd_entry"),
    }
    assert by_key[("r1", "cloud_essd_entry")]["price"] == pytest.approx(
        0.077599 / _GIB_TO_GB
    )
    assert by_key[("r1", "cloud_auto")]["unit"].value == "GB/month"
    vendor.log.assert_called_once()
    assert "cloud_auto in r2" in vendor.log.call_args.args[0]


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
        patch(
            "sc_crawler.vendors._alicloud._get_describe_price_storage_prices",
            return_value=[{"storage_id": "cloud_auto"}],
        ),
    ):
        items = inventory_storage_prices(vendor)
    assert items[0]["storage_id"] == "cloud_essd-pl1"
    # per GiB and hour in the API, per GB and month here
    assert items[0]["price"] == pytest.approx(0.0002 * 730 / _GIB_TO_GB)
    assert items[1] == {"storage_id": "cloud_auto"}
