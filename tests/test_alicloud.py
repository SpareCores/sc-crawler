from unittest.mock import Mock, patch

import pytest

from sc_crawler.inspector import _standardize_gpu_count
from sc_crawler.table_fields import (
    AcceleratorType,
    DatabaseHaLevel,
    DatabaseHaStrategy,
    DatabaseSecurityFeature,
    Disk,
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
    _call_with_retries,
    _compatible_storage_ids,
    _fetch_rds_offers,
    _fetch_rds_price,
    _get_zones,
    _gpu_manufacturer_of_family,
    _gpu_memory_by_spec,
    _instance_category,
    _is_transient_error,
    _local_disk_speed,
    _local_disks,
    _parse_instance_type_disk_categories,
    _parse_rds_available_zones,
    _parse_rds_price,
    _rds_class_editions,
    _rds_class_memory,
    _rds_class_status,
    _rds_class_vcpus,
    _rds_map_regions,
    _rds_multi_zone,
    _rds_region_prices,
    _rds_region_storage_prices,
    _rds_security_features,
    _RdsEndpointUnavailable,
    _RdsPriceUnavailable,
    _warn_unknown_category,
    _warn_unknown_local_disk_speed,
    inventory_database_prices,
    inventory_database_storage_prices,
    inventory_database_storages,
    inventory_databases,
    inventory_regions,
    inventory_server_prices_spot,
    inventory_servers,
    inventory_storages,
)


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
            return_value={"ecs.g7.large": ["cloud_essd", "cloud_ssd"]},
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
        "cloud_ssd",
    ]
    # no disk data for this instance type: unknown (None) and one summary warning
    assert by_id["ecs.gn5-c4g1.xlarge"]["compatible_storage_ids"] is None
    vendor.log.assert_called_once()
    assert "1 instance types" in vendor.log.call_args.args[0]
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


def test_alicloud_parse_instance_type_disk_categories_merges_zones():
    zones = [
        {
            "AvailableResources": {
                "ResourcesInfo": [
                    {
                        "DataDiskCategories": {
                            "supportedDataDiskCategory": ["cloud_essd"]
                        },
                        "InstanceTypes": {
                            "supportedInstanceType": ["ecs.g7.large", "ecs.c7.large"]
                        },
                    }
                ]
            }
        },
        {
            "AvailableResources": {
                "ResourcesInfo": [
                    {
                        "DataDiskCategories": {
                            "supportedDataDiskCategory": ["cloud_ssd", "cloud_essd"]
                        },
                        "InstanceTypes": {"supportedInstanceType": ["ecs.g7.large"]},
                    }
                ]
            }
        },
        {},
    ]
    assert _parse_instance_type_disk_categories(zones) == {
        "ecs.g7.large": ["cloud_essd", "cloud_ssd"],
        "ecs.c7.large": ["cloud_essd"],
    }


def test_alicloud_compatible_storage_ids():
    assert _compatible_storage_ids(["cloud_efficiency", "ephemeral_ssd"]) == [
        "cloud_efficiency"
    ]
    assert _compatible_storage_ids(["ephemeral_ssd"]) == []
    assert _compatible_storage_ids([]) == []


def test_alicloud_disk_category_mapping_matches_storage_ids():
    storage_ids = {s["storage_id"] for s in inventory_storages(Mock(vendor_id="a"))}
    mapped = {i for ids in _DISK_CATEGORY_TO_STORAGE_IDS.values() for i in ids}
    assert mapped == storage_ids


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


def _rds_zone(zone_id, categories, version="17.0"):
    return {
        "ZoneId": zone_id,
        "SupportedEngines": [
            {
                "Engine": "PostgreSQL",
                "SupportedEngineVersions": [
                    {
                        "Version": version,
                        "SupportedCategorys": [
                            {
                                "Category": category,
                                "SupportedStorageTypes": [
                                    {"StorageType": storage_type}
                                    for storage_type in storage_types
                                ],
                            }
                            for category, storage_types in categories.items()
                        ],
                    }
                ],
            }
        ],
    }


def test_alicloud_parse_rds_available_zones():
    offers = _parse_rds_available_zones(
        [
            # pair of zones, listed on their own as well
            _rds_zone("eu-central-1MAZ1(a,b)", {"HighAvailability": ["cloud_essd"]}),
            _rds_zone(
                "eu-central-1a",
                {
                    "cluster": ["cloud_essd", "cloud_auto"],
                    # phased-out disk types are not tracked
                    "HighAvailability": ["local_ssd", "cloud_ssd", "cloud_essd"],
                    "AlwaysOn": ["cloud_essd"],
                },
            ),
            _rds_zone("eu-central-1a", {"cluster": ["cloud_essd"]}, version="14.0"),
            _rds_zone("eu-central-1b", {"Basic": ["local_ssd"]}),
        ]
    )
    assert offers == {
        "cluster": {
            "eu-central-1a": {
                "versions": ["17.0", "14.0"],
                "storage_types": ["cloud_essd", "cloud_auto"],
                # disk types of each version
                "version_storage_types": {
                    "17.0": ["cloud_essd", "cloud_auto"],
                    "14.0": ["cloud_essd"],
                },
            }
        },
        "ha": {
            "eu-central-1a": {
                "versions": ["17.0"],
                "storage_types": ["cloud_essd"],
                "version_storage_types": {"17.0": ["cloud_essd"]},
            }
        },
    }


def test_alicloud_parse_rds_price_uses_unit_fees_in_cents():
    price = _parse_rds_price(
        {
            "PriceInfo": {
                "Currency": "USD",
                "OrderLines": {
                    "0": {
                        "moduleInstance": [
                            {
                                "moduleCode": "rds_storage",
                                "pricingModule": True,
                                "originUnitFee": "0.06",
                                "standPrice": 6.0,
                            },
                            {
                                "moduleCode": "rds_class",
                                "pricingModule": True,
                                "originUnitFee": "8.27",
                                "standPrice": 8.27,
                            },
                            {
                                "moduleCode": "rds_region",
                                "pricingModule": False,
                                "standPrice": 0,
                            },
                        ]
                    }
                },
            }
        }
    )
    assert price["currency"] == "USD"
    assert price["modules"] == pytest.approx(
        {"rds_storage": 0.0006, "rds_class": 0.0827}
    )
    assert _parse_rds_price({}) == {"currency": None, "modules": {}}


@pytest.mark.parametrize(
    "memory_class,expected",
    [
        (" 4GB（通用型）", 4096),
        ("16G (Intel SGX 安全增强)", 16384),
        (" 32GB（即将停售）", 32768),
        (" 24G（通用型）", 24576),
        ("", None),
    ],
)
def test_alicloud_rds_class_memory(memory_class, expected):
    assert _rds_class_memory({"MemoryClass": memory_class}) == expected


@pytest.mark.parametrize(
    "memory_class,orderable,expected",
    [
        (" 4GB（通用型）", True, Status.ACTIVE),
        (" 4GB（即将停售）", True, Status.PLANNED_FOR_RETIREMENT),
        (" 256GB（已停售）", True, Status.PLANNED_FOR_RETIREMENT),
        (" 256GB（已停售）", False, Status.RETIRED),
        # not orderable without an end of sale note: unknown, not listed
        (" 4GB（通用型）", False, None),
    ],
)
def test_alicloud_rds_class_status(memory_class, orderable, expected):
    assert _rds_class_status({"MemoryClass": memory_class}, orderable) == expected


@pytest.mark.parametrize(
    "cpu,expected", [("2", 2), ("4 ", 4), ("N/A", None), ("", None), (None, None)]
)
def test_alicloud_rds_class_vcpus(cpu, expected):
    assert _rds_class_vcpus({"Cpu": cpu}) == expected


def test_alicloud_rds_class_editions_prefer_the_end_of_sale_note():
    """The end of sale is not noted in all regions listing the instance type."""
    plain = {"ClassCode": "pg.x", "category": "Basic", "MemoryClass": " 4GB（通用型）"}
    noted = {**plain, "MemoryClass": " 4GB（即将停售）"}
    for specs in (
        {"r1": {"pg.x": plain}, "r2": {"pg.x": noted}, "r3": None},
        {"r1": {"pg.x": noted}, "r2": {"pg.x": plain}},
    ):
        assert _rds_class_editions(specs) == {"pg.x": ("basic", noted)}


def _rds_spec(class_code, category, group="通用型", cpu="2", memory=" 4GB", **kwargs):
    spec = {
        "ClassCode": class_code,
        "ClassGroup": group,
        "Cpu": cpu,
        "MemoryClass": memory,
        **kwargs,
    }
    if category:
        spec["category"] = category
    return spec


_RDS_PARAMS = {
    "zones": [
        {
            "zone_id": "eu-central-1a",
            "engine_version": "17.0",
            "storage_type": "cloud_essd",
        }
    ],
    "versions": ["14.0", "17.0"],
    "zone_versions": {"eu-central-1a": ["17.0", "14.0"]},
    "storage_ranges": {},
}
_RDS_PARAMS_MULTI_ZONE = {
    **_RDS_PARAMS,
    "zones": [
        *_RDS_PARAMS["zones"],
        {**_RDS_PARAMS["zones"][0], "zone_id": "eu-central-1b"},
    ],
    "zone_versions": {"eu-central-1a": ["17.0"], "eu-central-1b": ["17.0"]},
}
_RDS_STORAGE_TYPES_OFFERED = ["cloud_essd", "cloud_auto", "cloud_essd2", "cloud_essd3"]
_RDS_ZONE_OFFER = {
    "versions": ["14.0", "17.0"],
    "storage_types": _RDS_STORAGE_TYPES_OFFERED,
    "version_storage_types": {
        "14.0": _RDS_STORAGE_TYPES_OFFERED,
        "17.0": _RDS_STORAGE_TYPES_OFFERED,
    },
}
_RDS_OFFERS = {
    "eu-central-1": {
        "complete": True,
        "zones": {
            "basic": {"eu-central-1a": _RDS_ZONE_OFFER},
            "ha": {
                "eu-central-1a": _RDS_ZONE_OFFER,
                "eu-central-1b": _RDS_ZONE_OFFER,
            },
            "cluster": {
                "eu-central-1a": _RDS_ZONE_OFFER,
                "eu-central-1b": _RDS_ZONE_OFFER,
            },
        },
        "classes": {
            "basic": {"pg.n2.2c.1m": _RDS_PARAMS, "pg.n2.medium.1": _RDS_PARAMS},
            "ha": {
                # not orderable with the older engine version
                "pg.x4.large.2c": {**_RDS_PARAMS_MULTI_ZONE, "versions": ["17.0"]},
                # orderable in a single zone of the two offering the edition
                "pg.n2.2c.2m": _RDS_PARAMS,
            },
            "cluster": {
                "pg.x2e.medium.xc": _RDS_PARAMS_MULTI_ZONE,
                # orderable, but not listed by ListClasses
                "pg.n2.small.xc": _RDS_PARAMS,
            },
        },
    },
    # region without RDS for PostgreSQL
    "cn-nanjing": {"complete": True, "zones": {}, "classes": {}},
}
_RDS_SPECS = {
    "eu-central-1": {
        "pg.n2.2c.1m": _rds_spec(
            "pg.n2.2c.1m", "Basic", memory=" 4G（通用型）", ReferencePrice="8.27"
        ),
        "pg.n2.medium.1": _rds_spec(
            "pg.n2.medium.1", "Basic", memory=" 4GB（即将停售）", ReferencePrice="8.27"
        ),
        "pg.n8.8xlarge.1": _rds_spec(
            "pg.n8.8xlarge.1", "Basic", cpu="64", memory=" 512GB（已停售）"
        ),
        "pg.n2.2c.2m": _rds_spec("pg.n2.2c.2m", "HighAvailability"),
        "pg.x4.large.2c": _rds_spec(
            "pg.x4.large.2c",
            "HighAvailability",
            group="独享套餐",
            cpu="4 ",
            memory=" 16GB（独享）",
            ReferencePrice="76.34",
        ),
        "pg.x2e.medium.xc": _rds_spec(
            "pg.x2e.medium.xc",
            "Cluster",
            group="独享套餐",
            memory=" 4GB（独享型）",
            InstructionSetArch="arm",
        ),
        # not orderable and no end of sale note: skipped
        "pg.x4t.large.2c": _rds_spec(
            "pg.x4t.large.2c", "HighAvailability", group="Intel SGX 安全增强"
        ),
        # legacy instance type without an edition: skipped
        "rds.pg.s1.small": _rds_spec("rds.pg.s1.small", None, ReferencePrice="8.1"),
    },
    # ListClasses also returns instance types in regions without RDS
    "cn-nanjing": {
        "pg.n2.2c.1m": _rds_spec("pg.n2.2c.1m", "Basic", ReferencePrice="5.1"),
    },
}


def _rds_patches(rds_offers=_RDS_OFFERS, rds_specs=_RDS_SPECS):
    return (
        patch("sc_crawler.vendors._alicloud._get_rds_offers", return_value=rds_offers),
        patch(
            "sc_crawler.vendors._alicloud._get_rds_class_specs",
            return_value=rds_specs,
        ),
        patch(
            "sc_crawler.vendors._alicloud._rds_clients",
            return_value={region_id: Mock() for region_id in _RDS_OFFERS},
        ),
    )


def _inventory_rds_databases(rds_offers=_RDS_OFFERS, rds_specs=_RDS_SPECS):
    vendor = Mock(vendor_id="alicloud", session=None)
    offers, specs, clients = _rds_patches(rds_offers, rds_specs)
    with offers, specs, clients:
        rows = inventory_databases(vendor)
    return vendor, {row["database_id"]: row for row in rows}


def test_alicloud_inventory_databases_maps_editions_and_lifecycle():
    vendor, rows = _inventory_rds_databases()
    assert sorted(rows) == [
        "pg.n2.2c.1m",
        "pg.n2.2c.2m",
        "pg.n2.medium.1",
        "pg.n8.8xlarge.1",
        "pg.x2e.medium.xc",
        "pg.x4.large.2c",
    ]
    # orderable instance type without specs is reported once
    vendor.log.assert_called_once()
    assert "pg.n2.small.xc" in vendor.log.call_args.args[0]

    basic = rows["pg.n2.2c.1m"]
    assert basic["status"] == Status.ACTIVE
    assert basic["family"] == "General Purpose"
    assert basic["series"] == "pg.n2"
    assert basic["vcpus"] == 2
    assert basic["memory_amount"] == 4096
    assert basic["description"] == (
        "General Purpose Basic Edition (2 vCPUs, 4 GiB RAM)"
    )
    assert basic["api_reference_object"] == {
        "engine": "PostgreSQL",
        "instance_type": "pg.n2.2c.1m",
        "category": "Basic",
    }
    assert basic["engine_versions"] == ["14", "17"]
    assert basic["ha"] == [DatabaseHaLevel.NONE]
    assert basic["ha_strategy"] == [DatabaseHaStrategy.NONE]
    assert basic["max_read_replicas"] == 0
    # no log backups, so no point-in-time restore
    assert basic["scheduled_backups"] is True
    assert basic["continuous_backups"] == 0
    assert basic["sla"] is None
    assert basic["compatible_storage_ids"] == [
        "cloud_essd-basic",
        "cloud_essd2-basic",
        "cloud_essd3-basic",
        "cloud_auto-basic",
    ]
    # 10 GiB (Premium ESSD) to 64000 GiB, in GB
    assert basic["storage_extra_min"] == 11
    assert basic["storage_extra_max"] == 68719
    # service key only on general-purpose instance types
    assert (
        DatabaseSecurityFeature.CUSTOMER_MANAGED_KEYS not in basic["security_features"]
    )

    assert rows["pg.n2.medium.1"]["status"] == Status.PLANNED_FOR_RETIREMENT
    assert rows["pg.n8.8xlarge.1"]["status"] == Status.RETIRED

    ha = rows["pg.x4.large.2c"]
    assert ha["family"] == "Dedicated"
    assert ha["vcpus"] == 4
    assert ha["memory_amount"] == 16384
    assert ha["ha"] == [DatabaseHaLevel.MULTI_ZONE, DatabaseHaLevel.SINGLE_ZONE]
    assert ha["ha_strategy"] == [DatabaseHaStrategy.PASSIVE_STANDBY]
    assert ha["max_read_replicas"] == 32
    assert ha["continuous_backups"] == 730
    # only the engine versions the instance type is orderable with
    assert ha["engine_versions"] == ["17"]
    assert rows["pg.n8.8xlarge.1"]["engine_versions"] == []
    assert ha["sla"] == 99.99
    assert DatabaseSecurityFeature.CUSTOMER_MANAGED_KEYS in ha["security_features"]
    assert rows["pg.n2.2c.2m"]["sla"] == 99.95

    cluster = rows["pg.x2e.medium.xc"]
    assert cluster["ha_strategy"] == [DatabaseHaStrategy.READABLE_CLUSTER]
    assert cluster["max_read_replicas"] == 8
    assert cluster["description"] == (
        "Dedicated Cluster Edition (2 vCPUs, 4 GiB RAM, ARM)"
    )
    assert cluster["api_reference_object"]["category"] == "cluster"
    assert cluster["compatible_storage_ids"][0] == "cloud_essd-cluster"


def test_alicloud_inventory_database_prices_by_edition():
    vendor, rows = _inventory_rds_databases()
    vendor.databases = [
        Mock(
            database_id=row["database_id"],
            status=row["status"],
            api_reference_object=row["api_reference_object"],
        )
        for row in rows.values()
    ]

    def fetch_price(class_code, **kwargs):
        # pg.n2.2c.2m is listed as available, but has no pricing plan
        if class_code == "pg.n2.2c.2m":
            return None
        return {"currency": "USD", "modules": {"rds_class": 0.071}}

    offers, specs, clients = _rds_patches()
    with (
        offers,
        specs,
        clients,
        patch(
            "sc_crawler.vendors._alicloud._fetch_rds_price", side_effect=fetch_price
        ) as fetch,
    ):
        prices = inventory_database_prices(vendor)
    # only for the orderable instance types without a reference price
    assert sorted(call.kwargs["class_code"] for call in fetch.call_args_list) == [
        "pg.n2.2c.2m",
        "pg.x2e.medium.xc",
    ]
    assert {price["region_id"] for price in prices} == {"eu-central-1"}
    by_key = {
        (price["database_id"], price["ha"], price["ha_strategy"]): price["price"]
        for price in prices
    }
    assert by_key == pytest.approx(
        {
            # single zone offering the Basic Edition
            ("pg.n2.2c.1m", DatabaseHaLevel.NONE, DatabaseHaStrategy.NONE): 0.0827,
            ("pg.n2.medium.1", DatabaseHaLevel.NONE, DatabaseHaStrategy.NONE): 0.0827,
            # both nodes are covered by the price, in one or two zones
            (
                "pg.x4.large.2c",
                DatabaseHaLevel.MULTI_ZONE,
                DatabaseHaStrategy.PASSIVE_STANDBY,
            ): 0.7634,
            (
                "pg.x4.large.2c",
                DatabaseHaLevel.SINGLE_ZONE,
                DatabaseHaStrategy.PASSIVE_STANDBY,
            ): 0.7634,
            # billed per node, stored for 2 nodes
            (
                "pg.x2e.medium.xc",
                DatabaseHaLevel.MULTI_ZONE,
                DatabaseHaStrategy.READABLE_CLUSTER,
            ): 0.142,
            (
                "pg.x2e.medium.xc",
                DatabaseHaLevel.SINGLE_ZONE,
                DatabaseHaStrategy.READABLE_CLUSTER,
            ): 0.142,
        }
    )


def test_alicloud_inventory_database_storages_and_prices():
    vendor = Mock(vendor_id="alicloud")
    storages = {
        storage["database_storage_id"]: storage
        for storage in inventory_database_storages(vendor)
    }
    assert len(storages) == 12
    assert storages["cloud_essd-ha"]["name"] == "ESSD PL1 (High-availability Edition)"
    assert storages["cloud_essd-ha"]["min_size"] == 21
    assert storages["cloud_essd3-basic"]["min_size"] == 1611
    assert "2 nodes" in storages["cloud_auto-cluster"]["description"]
    vendor.database_storages = [
        Mock(database_storage_id=storage_id) for storage_id in storages
    ]

    unit_prices = {"basic": 0.0006, "ha": 0.001, "cluster": 0.0004}

    def fetch_price(edition_id, storage_type, **kwargs):
        if storage_type != "cloud_essd":
            return None
        return {"currency": "USD", "modules": {"rds_storage": unit_prices[edition_id]}}

    offers, specs, clients = _rds_patches()
    with (
        offers,
        specs,
        clients,
        patch("sc_crawler.vendors._alicloud._fetch_rds_price", side_effect=fetch_price),
    ):
        prices = inventory_database_storage_prices(vendor)
    assert {
        price["database_storage_id"]: price["price"] for price in prices
    } == pytest.approx(
        {
            "cloud_essd-basic": 0.0006 * 730,
            "cloud_essd-ha": 0.001 * 730,
            # per node, stored for 2 nodes
            "cloud_essd-cluster": 0.0004 * 2 * 730,
        }
    )
    assert {price["region_id"] for price in prices} == {"eu-central-1"}


@pytest.mark.parametrize(
    "rds_offers,rds_specs",
    [
        (
            {
                "eu-central-1": {"complete": False, "zones": {}, "classes": {}},
                "cn-nanjing": _RDS_OFFERS["cn-nanjing"],
            },
            _RDS_SPECS,
        ),
        (_RDS_OFFERS, {"eu-central-1": None, "cn-nanjing": _RDS_SPECS["cn-nanjing"]}),
    ],
)
def test_alicloud_inventory_databases_nothing_on_incomplete_lookups(
    rds_offers, rds_specs
):
    """Not found in a partial lookup is not a signal to retire or drop, so the
    previous records are left unchanged."""
    vendor, rows = _inventory_rds_databases(rds_offers, rds_specs)
    assert rows == {}
    warning = vendor.log.call_args_list[-1].args[0]
    assert "not known in all regions (eu-central-1)" in warning


def test_alicloud_inventory_databases_features_by_edition_and_family():
    vendor, rows = _inventory_rds_databases()
    assert rows["pg.n2.2c.1m"]["connection_pool"] is True
    assert rows["pg.x4.large.2c"]["connection_pool"] is True
    # no PgBouncer in the Cluster Edition
    assert rows["pg.x2e.medium.xc"]["connection_pool"] is False
    for family in ("General Purpose", None, "Unknown"):
        assert (
            DatabaseSecurityFeature.CUSTOMER_MANAGED_KEYS
            not in _rds_security_features(family)
        )
    for family in ("Dedicated", "Security Enhanced"):
        assert DatabaseSecurityFeature.CUSTOMER_MANAGED_KEYS in _rds_security_features(
            family
        )


def test_alicloud_rds_region_prices_try_more_zones():
    params = [
        {"zone_id": zone_id, "engine_version": "17.0", "storage_type": "cloud_essd"}
        for zone_id in ("a", "b", "c", "d")
    ]
    offer = {"classes": {"ha": {"pg.x": {"zones": params, "versions": ["17.0"]}}}}

    def fetch_price(zone_id, **kwargs):
        if zone_id == "b":
            return {"currency": "USD", "modules": {"rds_class": 0.5}}
        return None

    with patch(
        "sc_crawler.vendors._alicloud._fetch_rds_price", side_effect=fetch_price
    ) as fetch:
        prices = _rds_region_prices(Mock(), "r", offer, {}, {"pg.x": "ha"})
    assert prices == ({"pg.x": (0.5, "USD")}, set())
    assert [call.kwargs["zone_id"] for call in fetch.call_args_list] == ["a", "b"]

    with patch(
        "sc_crawler.vendors._alicloud._fetch_rds_price", return_value=None
    ) as fetch:
        # not sold
        assert _rds_region_prices(Mock(), "r", offer, {}, {"pg.x": "ha"}) == ({}, set())
    # bounded
    assert fetch.call_count == 3

    def fetch_unavailable(zone_id, **kwargs):
        if zone_id == "a":
            raise _RdsPriceUnavailable("Throttling.User")
        return None

    with patch(
        "sc_crawler.vendors._alicloud._fetch_rds_price", side_effect=fetch_unavailable
    ):
        # not priced due to transient errors
        assert _rds_region_prices(Mock(), "r", offer, {}, {"pg.x": "ha"}) == (
            {},
            {"pg.x"},
        )


def test_alicloud_rds_region_prices_stop_when_the_endpoint_is_unavailable():
    params = [{"zone_id": "a", "engine_version": "17.0", "storage_type": "cloud_essd"}]
    available = {"zones": params, "versions": ["17.0"]}
    offer = {"classes": {"ha": {"pg.x": available, "pg.y": available}}}
    editions = {"pg.x": "ha", "pg.y": "ha"}
    with patch(
        "sc_crawler.vendors._alicloud._fetch_rds_price",
        side_effect=_RdsEndpointUnavailable("Read timed out"),
    ) as fetch:
        assert _rds_region_prices(Mock(), "r", offer, {}, editions) == (
            {},
            {"pg.x", "pg.y"},
        )
    assert fetch.call_count == 1


def test_alicloud_inventory_databases_unknown_family():
    rds_specs = {
        "eu-central-1": {
            class_code: _rds_spec(class_code, "HighAvailability", group="新型")
            for class_code in ("pg.n2.2c.2m", "pg.x4.large.2c")
        }
    }
    vendor, rows = _inventory_rds_databases(rds_specs=rds_specs)
    for row in rows.values():
        assert row["family"] is None
        assert row["sla"] is None
        assert row["description"].startswith("High-availability Edition (")
    warnings = [c.args[0] for c in vendor.log.call_args_list if "新型" in c.args[0]]
    assert len(warnings) == 1


def test_alicloud_inventory_databases_storage_range_of_the_api():
    ranges = {"cloud_essd": (5, 128000)}
    rds_offers = {
        "eu-central-1": {
            **_RDS_OFFERS["eu-central-1"],
            "classes": {
                "basic": {"pg.n2.2c.1m": {**_RDS_PARAMS, "storage_ranges": ranges}}
            },
        }
    }
    _, rows = _inventory_rds_databases(rds_offers=rds_offers)
    assert rows["pg.n2.2c.1m"]["storage_extra_min"] == round(5 * _GIB_TO_GB)
    assert rows["pg.n2.2c.1m"]["storage_extra_max"] == round(128000 * _GIB_TO_GB)


def test_alicloud_inventory_database_prices_nothing_on_failed_regions():
    vendor, rows = _inventory_rds_databases()
    vendor.databases = [
        Mock(
            database_id=row["database_id"],
            status=row["status"],
            api_reference_object=row["api_reference_object"],
        )
        for row in rows.values()
    ]
    rds_offers = {
        **_RDS_OFFERS,
        "eu-west-1": {"complete": False, "zones": {}, "classes": {}},
    }
    offers, specs, clients = _rds_patches(rds_offers)
    with (
        offers,
        specs,
        patch(
            "sc_crawler.vendors._alicloud._rds_clients",
            return_value={region_id: Mock() for region_id in rds_offers},
        ),
        patch("sc_crawler.vendors._alicloud._fetch_rds_price", return_value=None),
    ):
        assert inventory_database_prices(vendor) == []
    assert "eu-west-1" in vendor.log.call_args.args[0]


def test_alicloud_inventory_databases_unknown_vcpus():
    rds_specs = {
        "eu-central-1": {
            "pg.n2.2c.1m": _rds_spec("pg.n2.2c.1m", "Basic", cpu="N/A"),
        }
    }
    vendor, rows = _inventory_rds_databases(rds_specs=rds_specs)
    assert rows["pg.n2.2c.1m"]["vcpus"] is None
    assert rows["pg.n2.2c.1m"]["description"] == (
        "General Purpose Basic Edition (4 GiB RAM)"
    )


def _rds_offers_client(zone_versions, orderable):
    """RDS client mock with the `{zone_id: [versions]}` of the Basic Edition,
    and the `{(zone_id, version): [class codes]}` orderable."""

    def engine(versions):
        return {
            "Engine": "PostgreSQL",
            "SupportedEngineVersions": [
                {
                    "Version": version,
                    "SupportedCategorys": [
                        {
                            "Category": "Basic",
                            "SupportedStorageTypes": [{"StorageType": "cloud_essd"}],
                        }
                    ],
                }
                for version in versions
            ],
        }

    client = Mock()
    client.describe_available_zones_with_options.return_value.body.to_map.return_value = {
        "AvailableZones": [
            {"ZoneId": zone_id, "SupportedEngines": [engine(versions)]}
            for zone_id, versions in zone_versions.items()
        ]
    }
    probes = []

    def available_classes(request, runtime):
        probes.append((request.zone_id, request.engine_version))
        found = orderable.get((request.zone_id, request.engine_version))
        if found is None:
            raise Exception(
                "Error: InvalidCondition.NotFound code: 404, No class found"
            )
        return Mock(
            body=Mock(
                to_map=Mock(
                    return_value={
                        "DBInstanceClasses": [
                            {
                                "DBInstanceClass": c,
                                # a smaller range in the zone z-b
                                "DBInstanceStorageRange": {
                                    "MinValue": 50 if request.zone_id == "z-b" else 20,
                                    "MaxValue": 32000
                                    if request.zone_id == "z-b"
                                    else 64000,
                                    "Step": 5,
                                },
                            }
                            for c in found
                        ]
                    }
                )
            )
        )

    client.describe_available_classes_with_options.side_effect = available_classes
    return client, probes


def test_alicloud_fetch_rds_offers_probes_each_older_version_once():
    """The newest and oldest versions in all zones, the rest once in any zone."""
    client, probes = _rds_offers_client(
        {
            "z-a": ["13.0", "14.0", "15.0", "16.0", "17.0"],
            "z-b": ["13.0", "14.0", "17.0"],
            "z-c": ["15.0", "16.0", "17.0"],
        },
        {
            ("z-a", "17.0"): ["pg.a"],
            ("z-b", "17.0"): ["pg.a"],
            ("z-c", "17.0"): ["pg.a"],
            # only orderable with a middle version not probed in its zone
            ("z-c", "16.0"): ["pg.missed"],
        },
    )
    classes = _fetch_rds_offers(client, "r")["classes"]["basic"]
    # known limitation of the compromise
    assert "pg.missed" not in classes
    assert sorted(probes) == [
        ("z-a", "13.0"),
        ("z-a", "14.0"),
        ("z-a", "16.0"),
        ("z-a", "17.0"),
        ("z-b", "13.0"),
        ("z-b", "17.0"),
        ("z-c", "15.0"),
        ("z-c", "17.0"),
    ]
    # the newest versions first
    assert probes[:3] == [("z-a", "17.0"), ("z-b", "17.0"), ("z-c", "17.0")]
    # the widest storage range of the zones, by the disk type probed
    assert classes["pg.a"]["storage_ranges"] == {"cloud_essd": (20, 64000)}


def test_alicloud_fetch_rds_offers_middle_versions_in_a_single_zone():
    """As in cn-shanghai: the Intel SGX instance types with PostgreSQL 13-15
    in 2 of the zones offering PostgreSQL 10-18."""
    versions = [f"{v}.0" for v in range(10, 19)]
    orderable = {(zone, "18.0"): ["pg.a"] for zone in ("z-b", "z-c", "z-l")}
    for version in ("13.0", "14.0", "15.0"):
        orderable[("z-b", version)] = ["pg.x4t.large.2c"]
        orderable[("z-l", version)] = ["pg.x4t.large.2c", "pg.x4t.2xlarge.2c"]
    client, probes = _rds_offers_client(
        {"z-b": versions, "z-c": versions, "z-l": versions}, orderable
    )
    classes = _fetch_rds_offers(client, "r")["classes"]["basic"]
    # the middle versions are only probed in the first zone offering the most
    # versions, then the newest one found in the other zones as well
    assert classes["pg.x4t.large.2c"]["zone_versions"] == {
        "z-b": ["15.0", "14.0", "13.0"],
        "z-l": ["15.0"],
    }
    assert _rds_multi_zone(classes["pg.x4t.large.2c"])
    # without its other versions in the other zones
    assert classes["pg.x4t.2xlarge.2c"]["zone_versions"] == {"z-l": ["15.0"]}
    assert not _rds_multi_zone(classes["pg.x4t.2xlarge.2c"])
    assert _rds_multi_zone(classes["pg.a"])
    # 3 newest, 3 oldest, 7 middle versions and 2 follow-ups instead of 27 calls
    assert len(probes) == 15
    assert probes[-2:] == [("z-c", "15.0"), ("z-l", "15.0")]


def test_alicloud_fetch_rds_offers_middle_versions_missed():
    """Known limitation: not orderable in the zone the version was probed in."""
    versions = [f"{v}.0" for v in range(10, 19)]
    orderable = {(zone, "18.0"): ["pg.a"] for zone in ("z-b", "z-l")}
    orderable[("z-l", "13.0")] = ["pg.x4t.2xlarge.2c"]
    client, probes = _rds_offers_client({"z-b": versions, "z-l": versions}, orderable)
    classes = _fetch_rds_offers(client, "r")["classes"]["basic"]
    assert "pg.x4t.2xlarge.2c" not in classes


def test_alicloud_fetch_rds_offers_finds_classes_of_the_oldest_version_in_all_zones():
    """E.g. the Intel SGX instance types with PostgreSQL 13 only in some zones."""
    versions = ["13.0", "17.0", "18.0"]
    client, probes = _rds_offers_client(
        {"z-b": versions, "z-c": versions, "z-l": versions},
        {
            ("z-b", "18.0"): ["pg.a"],
            ("z-b", "17.0"): ["pg.a"],
            ("z-l", "18.0"): ["pg.a"],
            ("z-b", "13.0"): ["pg.a", "pg.x4t.large.2c"],
            ("z-l", "13.0"): ["pg.a", "pg.x4t.large.2c", "pg.x4t.2xlarge.2c"],
        },
    )
    classes = _fetch_rds_offers(client, "r")["classes"]["basic"]

    def zones(class_code):
        return [
            (params["zone_id"], params["engine_version"])
            for params in classes[class_code]["zones"]
        ]

    # orderable in multiple zones with the oldest version
    assert zones("pg.x4t.large.2c") == [("z-b", "13.0"), ("z-l", "13.0")]
    assert classes["pg.x4t.large.2c"]["versions"] == ["13.0"]
    # not orderable with the oldest version in the zone probed for 17.0
    assert zones("pg.x4t.2xlarge.2c") == [("z-l", "13.0")]
    # the newest version found in a zone is kept for the price queries
    assert zones("pg.a") == [("z-b", "18.0"), ("z-l", "18.0")]
    assert sorted(classes["pg.a"]["versions"], key=float) == versions
    assert _rds_multi_zone(classes["pg.x4t.large.2c"])
    assert not _rds_multi_zone(classes["pg.x4t.2xlarge.2c"])


def test_alicloud_rds_multi_zone_needs_a_shared_engine_version():
    assert _rds_multi_zone({"zone_versions": {"a": ["13.0"], "b": ["13.0", "18.0"]}})
    # orderable in two zones, but with different engine versions
    assert not _rds_multi_zone({"zone_versions": {"a": ["13.0"], "b": ["18.0"]}})
    assert not _rds_multi_zone({"zone_versions": {"a": ["13.0", "18.0"]}})


def test_alicloud_fetch_rds_price_warns_when_throttled():
    client = Mock()
    client.describe_price_with_options.side_effect = Exception("Throttling.User")
    with (
        patch("sc_crawler.vendors._alicloud.sleep"),
        patch("sc_crawler.vendors._alicloud.logger") as logger,
        patch("sc_crawler.vendors._alicloud._logged_error_codes", set()),
        pytest.raises(_RdsEndpointUnavailable),
    ):
        _fetch_rds_price(client, "r", "pg.x", "basic", "z", "17.0", "cloud_essd", 20)
    logger.warning.assert_called_once()

    # other errors (e.g. a missing permission): no price, not "not sold" either
    client.describe_price_with_options.side_effect = Exception("InvalidParameter")
    with (
        patch("sc_crawler.vendors._alicloud.logger") as logger,
        patch("sc_crawler.vendors._alicloud._logged_error_codes", set()),
        pytest.raises(_RdsPriceUnavailable) as error,
    ):
        _fetch_rds_price(client, "r", "pg.x", "basic", "z", "17.0", "cloud_essd", 20)
    assert not isinstance(error.value, _RdsEndpointUnavailable)
    logger.warning.assert_called_once()


def test_alicloud_rds_map_regions_results_are_kept_for_the_session():
    vendor = Mock(session=Mock())
    fetch = Mock(return_value={"x": 1})
    with (
        patch(
            "sc_crawler.vendors._alicloud._rds_clients",
            return_value={"r1": Mock()},
        ),
        patch("sc_crawler.vendors._alicloud._rds_region_results", {}),
        # no disk cache of the API calls
        patch("sc_crawler.vendors._alicloud.cachier", lambda **kwargs: lambda f: f),
    ):
        name = "test lookup kept for the session"
        assert _rds_map_regions(vendor, name, fetch, None) == {"r1": {"x": 1}}
        _rds_map_regions(vendor, name, fetch, None)
        assert fetch.call_count == 1
        # a new run with a new session
        vendor.session = Mock()
        _rds_map_regions(vendor, name, fetch, None)
        assert fetch.call_count == 2


def test_alicloud_rds_map_regions_retries_only_the_failed_regions():
    vendor = Mock(session=Mock())
    calls = []

    def fetch(client, region_id):
        calls.append(region_id)
        if region_id == "r2" and calls.count("r2") == 1:
            raise _tea_error("ServiceUnavailable", 503)
        return {"region": region_id}

    with (
        patch(
            "sc_crawler.vendors._alicloud._rds_clients",
            return_value={"r1": Mock(), "r2": Mock()},
        ),
        patch("sc_crawler.vendors._alicloud._rds_region_results", {}),
        patch("sc_crawler.vendors._alicloud.cachier", lambda **kwargs: lambda f: f),
    ):
        name = "test lookup retried per region"
        assert _rds_map_regions(vendor, name, fetch, "failed") == {
            "r1": {"region": "r1"},
            "r2": "failed",
        }
        assert _rds_map_regions(vendor, name, fetch, "failed") == {
            "r1": {"region": "r1"},
            "r2": {"region": "r2"},
        }
        assert sorted(calls) == ["r1", "r2", "r2"]


def test_alicloud_rds_map_regions_raises_on_bugs(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    with (
        patch("sc_crawler.vendors._alicloud._rds_clients", return_value={"r1": Mock()}),
        patch("sc_crawler.vendors._alicloud._rds_region_results", {}),
        patch("sc_crawler.vendors._alicloud.cachier", lambda **kwargs: lambda f: f),
        pytest.raises(KeyError),
    ):
        _rds_map_regions(
            Mock(session=Mock()), "test bug", Mock(side_effect=KeyError), {}
        )


def test_alicloud_storage_price_uses_a_zone_offering_the_disk_type():
    """Premium ESSD is only offered in the second zone of the instance type."""
    params_a = {"zone_id": "a", "engine_version": "17.0", "storage_type": "cloud_essd"}
    params_b = {**params_a, "zone_id": "b"}
    offer = {
        "zones": {
            "ha": {
                "a": {
                    "versions": ["17.0"],
                    "storage_types": ["cloud_essd"],
                    "version_storage_types": {"17.0": ["cloud_essd"]},
                },
                "b": {
                    "versions": ["17.0"],
                    "storage_types": ["cloud_essd", "cloud_auto"],
                    "version_storage_types": {"17.0": ["cloud_essd", "cloud_auto"]},
                },
            }
        },
        "classes": {
            "ha": {
                "pg.n2.2c.2m": {
                    "zones": [params_a, params_b],
                    "versions": ["17.0"],
                    "zone_versions": {"a": ["17.0"], "b": ["17.0"]},
                }
            }
        },
    }
    with patch(
        "sc_crawler.vendors._alicloud._fetch_rds_price",
        return_value={"currency": "USD", "modules": {"rds_storage": 0.001}},
    ) as fetch:
        prices, failed = _rds_region_storage_prices(Mock(), "eu-central-1", offer, {})
    assert sorted(prices) == ["cloud_auto-ha", "cloud_essd-ha"]
    assert failed == set()
    zones = {
        call.kwargs["storage_type"]: call.kwargs["zone_id"]
        for call in fetch.call_args_list
    }
    assert zones == {"cloud_essd": "a", "cloud_auto": "b"}


def test_alicloud_call_with_retries_on_transient_errors():
    call = Mock(
        side_effect=[
            Exception("Connection to ecs.cn-chengdu.aliyuncs.com timed out."),
            Exception("('Connection aborted.', ConnectionResetError(54))"),
            "ok",
        ]
    )
    with patch("sc_crawler.vendors._alicloud.sleep") as sleep:
        assert _call_with_retries(call) == "ok"
    assert [c.args[0] for c in sleep.call_args_list] == [2, 3]

    # not transient, or out of attempts
    for error, calls in (("InvalidParameter", 1), ("Read timed out", 5)):
        call = Mock(side_effect=Exception(error))
        with patch("sc_crawler.vendors._alicloud.sleep"), pytest.raises(Exception):
            _call_with_retries(call)
        assert call.call_count == calls


def test_alicloud_get_zones_retries_timeouts():
    client = Mock()
    response = Mock()
    response.body.to_map.return_value = {"Zones": {"Zone": [{"ZoneId": "a"}]}}
    client.describe_zones.side_effect = [Exception("Read timed out."), response]
    with patch("sc_crawler.vendors._alicloud.sleep"):
        assert _get_zones(client, "cn-chengdu") == [{"ZoneId": "a"}]


def test_alicloud_storage_price_uses_an_older_engine_version_offering_the_disk_type():
    """Premium ESSD is only offered with the older engine version of the zone."""
    offer = {
        "zones": {
            "ha": {
                "a": {
                    "versions": ["17.0", "14.0"],
                    "storage_types": ["cloud_essd", "cloud_essd3"],
                    "version_storage_types": {
                        "17.0": ["cloud_essd"],
                        "14.0": ["cloud_essd3"],
                    },
                }
            }
        },
        "classes": {
            "ha": {
                "pg.x": {
                    "zones": [
                        {
                            "zone_id": "a",
                            "engine_version": "17.0",
                            "storage_type": "cloud_essd",
                        }
                    ],
                    "versions": ["17.0", "14.0"],
                    "zone_versions": {"a": ["17.0", "14.0"]},
                }
            }
        },
    }
    with patch(
        "sc_crawler.vendors._alicloud._fetch_rds_price",
        return_value={"currency": "USD", "modules": {"rds_storage": 0.001}},
    ) as fetch:
        prices, failed = _rds_region_storage_prices(Mock(), "r", offer, {})
    assert sorted(prices) == ["cloud_essd-ha", "cloud_essd3-ha"]
    versions = {
        call.kwargs["storage_type"]: call.kwargs["engine_version"]
        for call in fetch.call_args_list
    }
    assert versions == {"cloud_essd": "17.0", "cloud_essd3": "14.0"}

    # not priced due to transient errors
    with patch(
        "sc_crawler.vendors._alicloud._fetch_rds_price",
        side_effect=_RdsPriceUnavailable("Read timed out"),
    ):
        assert _rds_region_storage_prices(Mock(), "r", offer, {}) == (
            {},
            {"cloud_essd-ha", "cloud_essd3-ha"},
        )


def _tea_error(code, status_code):
    from Tea.exceptions import TeaException

    return TeaException(
        {
            "code": code,
            "message": f"{code} message",
            "data": {"statusCode": status_code, "Code": code},
        }
    )


def test_alicloud_server_errors_are_transient():
    assert _is_transient_error(_tea_error("RequestMetaDataFailed", 500))
    assert _is_transient_error(_tea_error("ExternalFailure", 500))
    assert not _is_transient_error(_tea_error("Price.PricingPlanResultNotFound", 400))
    assert _is_transient_error(Exception("Throttling.User"))
    assert not _is_transient_error(Exception("InvalidParameter"))


def test_alicloud_fetch_rds_price_not_sold_and_errors_logged_once():
    client = Mock()
    # an instance type not purchasable in the zone: no price, no warning
    client.describe_price_with_options.side_effect = _tea_error(
        "Commodity.InvalidComponent", 400
    )
    with patch("sc_crawler.vendors._alicloud.logger") as logger:
        assert (
            _fetch_rds_price(
                client, "r", "pg.x", "basic", "z", "17.0", "cloud_essd", 20
            )
            is None
        )
    logger.warning.assert_not_called()

    # other errors: a warning only for the first one of each error code
    client.describe_price_with_options.side_effect = _tea_error("Forbidden.RAM", 403)
    with (
        patch("sc_crawler.vendors._alicloud.logger") as logger,
        patch("sc_crawler.vendors._alicloud._logged_error_codes", set()),
    ):
        for _ in range(3):
            with pytest.raises(_RdsPriceUnavailable):
                _fetch_rds_price(
                    client, "r", "pg.x", "basic", "z", "17.0", "cloud_essd", 20
                )
    logger.warning.assert_called_once()
    assert "Forbidden.RAM" in logger.warning.call_args.args[0]
    assert logger.debug.call_count == 2


def test_alicloud_fetch_rds_price_retries_service_failures():
    client = Mock()
    client.describe_price_with_options.side_effect = _tea_error(
        "RequestMetaDataFailed", 500
    )
    with (
        patch("sc_crawler.vendors._alicloud.sleep"),
        pytest.raises(_RdsPriceUnavailable),
    ):
        _fetch_rds_price(client, "r", "pg.x", "basic", "z", "17.0", "cloud_essd", 20)
    assert client.describe_price_with_options.call_count == 15

    # no pricing plan: not retried, no price
    client = Mock()
    client.describe_price_with_options.side_effect = _tea_error(
        "Price.PricingPlanResultNotFound", 400
    )
    assert (
        _fetch_rds_price(client, "r", "pg.x", "basic", "z", "17.0", "cloud_essd", 20)
        is None
    )
    assert client.describe_price_with_options.call_count == 1


def test_alicloud_fetch_rds_offers_keeps_the_newest_version_found_in_a_zone():
    """Probed with the oldest version before the middle ones."""
    versions = ["13.0", "14.0", "15.0", "16.0", "17.0"]
    orderable = {
        ("z-a", "17.0"): ["pg.a"],
        ("z-a", "13.0"): ["pg.b"],
        ("z-a", "15.0"): ["pg.b"],
    }
    client, _ = _rds_offers_client({"z-a": versions}, orderable)
    classes = _fetch_rds_offers(client, "r")["classes"]["basic"]
    assert classes["pg.b"]["zones"] == [
        {"zone_id": "z-a", "engine_version": "15.0", "storage_type": "cloud_essd"}
    ]
    assert classes["pg.a"]["zones"][0]["engine_version"] == "17.0"


def test_alicloud_inventory_databases_compatible_storage_of_the_class():
    """Premium ESSD only offered with an engine version the class is not orderable with."""
    zone_offer = {
        **_RDS_ZONE_OFFER,
        "version_storage_types": {
            "14.0": _RDS_STORAGE_TYPES_OFFERED,
            "17.0": ["cloud_essd", "cloud_essd2"],
        },
    }
    region = _RDS_OFFERS["eu-central-1"]
    rds_offers = {
        **_RDS_OFFERS,
        "eu-central-1": {
            **region,
            "zones": {
                **region["zones"],
                "ha": {"eu-central-1a": zone_offer, "eu-central-1b": zone_offer},
            },
        },
    }
    _, rows = _inventory_rds_databases(rds_offers)
    # orderable with 17.0 only
    ha = rows["pg.x4.large.2c"]
    assert ha["compatible_storage_ids"] == ["cloud_essd-ha", "cloud_essd2-ha"]
    assert ha["storage_extra_min"] == round(20 * 1024**3 / 1000**3)
    # orderable with 14.0 as well
    assert rows["pg.n2.2c.2m"]["compatible_storage_ids"] == [
        "cloud_essd-ha",
        "cloud_essd2-ha",
        "cloud_essd3-ha",
        "cloud_auto-ha",
    ]
    # not orderable: unknown
    assert rows["pg.n8.8xlarge.1"]["status"] == Status.RETIRED
    assert rows["pg.n8.8xlarge.1"]["compatible_storage_ids"] is None
    assert rows["pg.n8.8xlarge.1"]["storage_extra_min"] is None


def test_alicloud_inventory_databases_retries_the_failed_lookups():
    incomplete = {
        **_RDS_OFFERS,
        "eu-west-1": {"complete": False, "zones": {}, "classes": {}},
    }
    recovered = {
        **_RDS_OFFERS,
        "eu-west-1": {
            "complete": True,
            "zones": {"basic": {"eu-west-1a": _RDS_ZONE_OFFER}},
            "classes": {"basic": {"pg.n4.2c.1m": _RDS_PARAMS}},
        },
    }
    specs = {
        **_RDS_SPECS,
        "eu-west-1": {"pg.n4.2c.1m": _rds_spec("pg.n4.2c.1m", "Basic")},
    }
    _, other_specs, clients = _rds_patches(rds_specs=specs)
    with (
        patch(
            "sc_crawler.vendors._alicloud._get_rds_offers",
            side_effect=[incomplete, recovered],
        ) as offers,
        other_specs,
        clients,
    ):
        rows = inventory_databases(Mock(vendor_id="alicloud", session=None))
    assert offers.call_count == 2
    assert "pg.n4.2c.1m" in {row["database_id"] for row in rows}


def test_alicloud_inventory_database_prices_nothing_on_failed_quotes():
    """An instance type failing to be priced leaves all the prices unchanged."""
    vendor, rows = _inventory_rds_databases()
    vendor.databases = [
        Mock(
            database_id=row["database_id"],
            status=row["status"],
            api_reference_object=row["api_reference_object"],
        )
        for row in rows.values()
    ]
    offers, specs, clients = _rds_patches()
    with (
        offers,
        specs,
        clients,
        patch(
            "sc_crawler.vendors._alicloud._fetch_rds_price",
            side_effect=_RdsPriceUnavailable("Forbidden.RAM"),
        ),
    ):
        assert inventory_database_prices(vendor) == []
    assert "2 instance types" in vendor.log.call_args.args[0]


def test_alicloud_storage_price_tries_other_zones_of_the_same_class():
    """The quote in the first zone has no storage price, the second one has."""
    zone_offer = {
        "versions": ["17.0"],
        "storage_types": ["cloud_essd"],
        "version_storage_types": {"17.0": ["cloud_essd"]},
    }
    offer = {
        "zones": {"ha": {"a": zone_offer, "b": zone_offer}},
        "classes": {
            "ha": {
                "pg.n2.2c.2m": {
                    "zones": [],
                    "versions": ["17.0"],
                    "zone_versions": {"a": ["17.0"], "b": ["17.0"]},
                }
            }
        },
    }

    def fetch_price(zone_id, **kwargs):
        if zone_id == "a":
            return {"currency": "USD", "modules": {}}
        return {"currency": "USD", "modules": {"rds_storage": 0.001}}

    with patch(
        "sc_crawler.vendors._alicloud._fetch_rds_price", side_effect=fetch_price
    ) as fetch:
        prices, failed = _rds_region_storage_prices(Mock(), "eu-central-1", offer, {})
    assert prices == {"cloud_essd-ha": (0.001, "USD")}
    assert [call.kwargs["zone_id"] for call in fetch.call_args_list] == ["a", "b"]


def test_alicloud_inventory_regions_closed_down_are_inactive():
    regions = [
        {"RegionId": "eu-central-1", "LocalName": "Germany (Frankfurt)"},
        {
            "RegionId": "cn-nanjing",
            "LocalName": "China (Nanjing - Local Region) Closed Down",
        },
    ]
    with patch("sc_crawler.vendors._alicloud._get_regions", return_value=regions):
        items = inventory_regions(Mock(vendor_id="alicloud"))
    assert {item["region_id"]: item["status"] for item in items} == {
        "eu-central-1": Status.ACTIVE,
        "cn-nanjing": Status.INACTIVE,
    }


def test_alicloud_inventory_server_prices_spot_keeps_the_ones_not_sampled():
    from sc_crawler.table_fields import Allocation

    def server_price(server_id, allocation, price=None):
        row = {
            "region_id": "r1",
            "zone_id": "r1a",
            "server_id": server_id,
            "allocation": allocation,
            "status": Status.ACTIVE,
            "price": price,
        }
        return Mock(**row, model_dump=Mock(return_value=row))

    vendor = Mock(
        vendor_id="alicloud",
        server_prices=[
            *(
                server_price(server_id, Allocation.ONDEMAND)
                for server_id in ("ecs.spot", "ecs.nospot", "ecs.unknown")
            ),
            # resampled
            server_price("ecs.spot", Allocation.SPOT, 0.5),
            # sampled without a spot price
            server_price("ecs.nospot", Allocation.SPOT, 0.5),
            # not sampled (failed lookup)
            server_price("ecs.unknown", Allocation.SPOT, 0.5),
            # not sold on-demand anymore
            server_price("ecs.gone", Allocation.SPOT, 0.5),
        ],
    )

    def instance_price(instance_type, **kwargs):
        if instance_type == "ecs.unknown":
            return None
        discount = (
            "Preemptible Instance discount" if instance_type == "ecs.spot" else ""
        )
        body = Mock()
        body.price_info.rules.rule = [Mock(description=discount)]
        body.price_info.price.detail_infos.detail_info = [
            Mock(resource="instanceType", trade_price=0.1)
        ]
        body.price_info.price.currency = "USD"
        return body

    with (
        patch("sc_crawler.vendors._alicloud._ecs_clients", return_value={"r1": Mock()}),
        patch(
            "sc_crawler.vendors._alicloud._get_instance_price",
            side_effect=instance_price,
        ),
    ):
        items = inventory_server_prices_spot(vendor)
    assert {(item["server_id"], item["price"]) for item in items} == {
        ("ecs.spot", 0.1),
        ("ecs.unknown", 0.5),
    }
    vendor.set_table_rows_inactive.assert_not_called()
