from unittest.mock import Mock, patch

import pytest

from sc_crawler.inspector import _standardize_gpu_count
from sc_crawler.table_fields import (
    AcceleratorType,
    DatabaseHaLevel,
    DatabaseHaStrategy,
    DatabaseSecurityFeature,
    Status,
)
from sc_crawler.vendor_helpers import server_status_from_availability_categories
from sc_crawler.vendors._alicloud import (
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_LIFECYCLE,
    _ALICLOUD_STATUS_CATEGORY_TO_SERVER_STATUS,
    _DISK_CATEGORY_TO_STORAGE_IDS,
    _accelerator_type,
    _compatible_storage_ids,
    _gpu_manufacturer_of_family,
    _gpu_memory_by_spec,
    _instance_category,
    _parse_instance_type_disk_categories,
    _parse_rds_available_zones,
    _parse_rds_price,
    _rds_class_memory,
    _rds_class_status,
    _rds_region_storage_prices,
    _warn_unknown_category,
    inventory_database_prices,
    inventory_database_storage_prices,
    inventory_database_storages,
    inventory_databases,
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
            }
        },
        "ha": {
            "eu-central-1a": {"versions": ["17.0"], "storage_types": ["cloud_essd"]}
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
    "memory_class,expected",
    [
        (" 4GB（通用型）", Status.ACTIVE),
        (" 4GB（即将停售）", Status.PLANNED_FOR_RETIREMENT),
        (" 256GB（已停售）", Status.PLANNED_FOR_RETIREMENT),
    ],
)
def test_alicloud_rds_class_status_of_incomplete_lookup(memory_class, expected):
    """Not found in a partial lookup is not a signal to retire or drop."""
    spec = {"MemoryClass": memory_class}
    assert _rds_class_status(spec, False, complete=False) == expected


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
}
_RDS_ZONE_OFFER = {
    "versions": ["14.0", "17.0"],
    "storage_types": ["cloud_essd", "cloud_auto", "cloud_essd2", "cloud_essd3"],
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
                "pg.x4.large.2c": {**_RDS_PARAMS, "versions": ["17.0"]},
                "pg.n2.2c.2m": _RDS_PARAMS,
            },
            "cluster": {
                "pg.x2e.medium.xc": _RDS_PARAMS,
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


def _rds_patches(rds_offers=_RDS_OFFERS):
    return (
        patch("sc_crawler.vendors._alicloud._get_rds_offers", return_value=rds_offers),
        patch(
            "sc_crawler.vendors._alicloud._get_rds_class_specs",
            return_value=_RDS_SPECS,
        ),
        patch(
            "sc_crawler.vendors._alicloud._rds_clients",
            return_value={region_id: Mock() for region_id in _RDS_OFFERS},
        ),
    )


def _inventory_rds_databases(rds_offers=_RDS_OFFERS):
    vendor = Mock(vendor_id="alicloud")
    offers, specs, clients = _rds_patches(rds_offers)
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


def test_alicloud_inventory_databases_keeps_classes_of_failed_regions():
    rds_offers = {
        "eu-central-1": {"complete": False, "zones": {}, "classes": {}},
        "cn-nanjing": _RDS_OFFERS["cn-nanjing"],
    }
    vendor, rows = _inventory_rds_databases(rds_offers)
    assert rows["pg.n2.2c.1m"]["status"] == Status.ACTIVE
    assert rows["pg.n2.medium.1"]["status"] == Status.PLANNED_FOR_RETIREMENT
    assert rows["pg.n8.8xlarge.1"]["status"] == Status.PLANNED_FOR_RETIREMENT
    assert "not known in all regions" in vendor.log.call_args.args[0]


def test_alicloud_storage_price_uses_a_zone_offering_the_disk_type():
    """Premium ESSD is only offered in the second zone of the instance type."""
    params_a = {"zone_id": "a", "engine_version": "17.0", "storage_type": "cloud_essd"}
    params_b = {**params_a, "zone_id": "b"}
    offer = {
        "zones": {
            "ha": {
                "a": {"versions": ["17.0"], "storage_types": ["cloud_essd"]},
                "b": {
                    "versions": ["17.0"],
                    "storage_types": ["cloud_essd", "cloud_auto"],
                },
            }
        },
        "classes": {
            "ha": {"pg.n2.2c.2m": {"zones": [params_a, params_b], "versions": ["17.0"]}}
        },
    }
    with patch(
        "sc_crawler.vendors._alicloud._fetch_rds_price",
        return_value={"currency": "USD", "modules": {"rds_storage": 0.001}},
    ) as fetch:
        prices = _rds_region_storage_prices(Mock(), "eu-central-1", offer, {})
    assert sorted(prices) == ["cloud_auto-ha", "cloud_essd-ha"]
    zones = {
        call.kwargs["storage_type"]: call.kwargs["zone_id"]
        for call in fetch.call_args_list
    }
    assert zones == {"cloud_essd": "a", "cloud_auto": "b"}
