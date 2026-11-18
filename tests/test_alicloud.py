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
    _call_with_retries,
    _compatible_storage_ids,
    _fetch_rds_offers,
    _fetch_rds_price,
    _get_zones,
    _gpu_manufacturer_of_family,
    _gpu_memory_by_spec,
    _instance_category,
    _parse_instance_type_disk_categories,
    _parse_rds_available_zones,
    _parse_rds_price,
    _RdsPriceUnavailable,
    _expire_previous_rows,
    _previous_active_prices,
    _previous_rows,
    _rds_class_editions,
    _rds_class_memory,
    _rds_class_status,
    _rds_class_vcpus,
    _rds_map_regions,
    _rds_multi_zone,
    _rds_region_prices,
    _rds_region_storage_prices,
    _rds_security_features,
    _warn_unknown_category,
    inventory_database_prices,
    inventory_database_storage_prices,
    inventory_database_storages,
    inventory_databases,
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


def _inventory_rds_databases(rds_offers=_RDS_OFFERS, rds_specs=_RDS_SPECS, previous=()):
    vendor = Mock(vendor_id="alicloud", session=None)
    offers, specs, clients = _rds_patches(rds_offers, rds_specs)
    with (
        offers,
        specs,
        clients,
        patch(
            "sc_crawler.vendors._alicloud._previous_orderable_databases",
            return_value={row["database_id"]: row for row in previous},
        ),
    ):
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


def _previous_database(database_id, status=Status.ACTIVE):
    return {
        "database_id": database_id,
        "status": status,
        "engine_versions": ["16", "17"],
    }


def test_alicloud_inventory_databases_keeps_previous_classes_of_failed_regions():
    """Not found in a partial lookup is not a signal to retire or drop."""
    rds_offers = {
        "eu-central-1": {"complete": False, "zones": {}, "classes": {}},
        "cn-nanjing": _RDS_OFFERS["cn-nanjing"],
    }
    previous = [
        _previous_database("pg.n2.2c.1m"),
        _previous_database("pg.n2.medium.1", Status.PLANNED_FOR_RETIREMENT),
    ]
    vendor, rows = _inventory_rds_databases(rds_offers, previous=previous)
    # kept as they were, also with their engine versions
    assert rows["pg.n2.2c.1m"] == previous[0]
    assert rows["pg.n2.medium.1"]["status"] == Status.PLANNED_FOR_RETIREMENT
    # not orderable before either: retired by its end of sale note
    assert rows["pg.n8.8xlarge.1"]["status"] == Status.RETIRED
    assert rows["pg.n8.8xlarge.1"]["engine_versions"] == []
    # never orderable before: not listed as orderable
    assert "pg.x4.large.2c" not in rows
    assert "not known in all regions" in vendor.log.call_args_list[0].args[0]


def test_alicloud_inventory_databases_keeps_previous_classes_without_specs():
    """Orderable, but the specs of all regions listing it failed to be looked up."""
    rds_specs = {"eu-central-1": None, "cn-nanjing": _RDS_SPECS["cn-nanjing"]}
    previous = [_previous_database("pg.x4.large.2c")]
    vendor, rows = _inventory_rds_databases(rds_specs=rds_specs, previous=previous)
    assert rows["pg.x4.large.2c"] == previous[0]
    # specs from the other region
    assert rows["pg.n2.2c.1m"]["status"] == Status.ACTIVE
    # not known before, and without specs
    assert "pg.n2.2c.2m" not in rows


def test_alicloud_inventory_databases_keeps_previous_classes_not_found_at_all():
    """Neither orderable, nor listed in the regions with specs."""
    rds_offers = {
        "eu-central-1": {"complete": False, "zones": {}, "classes": {}},
        "cn-nanjing": _RDS_OFFERS["cn-nanjing"],
    }
    rds_specs = {"eu-central-1": None, "cn-nanjing": _RDS_SPECS["cn-nanjing"]}
    previous = [_previous_database("pg.x4.large.2c")]
    vendor, rows = _inventory_rds_databases(rds_offers, rds_specs, previous)
    assert rows["pg.x4.large.2c"] == previous[0]


def test_alicloud_inventory_databases_keeps_the_planned_retirement_without_specs():
    """The end of sale might be noted in the regions without specs."""
    rds_specs = {
        "eu-central-1": {"pg.n2.2c.1m": _RDS_SPECS["eu-central-1"]["pg.n2.2c.1m"]},
        "cn-nanjing": None,
    }
    previous = [_previous_database("pg.n2.2c.1m", Status.PLANNED_FOR_RETIREMENT)]
    vendor, rows = _inventory_rds_databases(rds_specs=rds_specs, previous=previous)
    assert rows["pg.n2.2c.1m"]["status"] == Status.PLANNED_FOR_RETIREMENT
    # complete specs: recalculated
    vendor, rows = _inventory_rds_databases(previous=previous)
    assert rows["pg.n2.2c.1m"]["status"] == Status.ACTIVE


@pytest.mark.parametrize(
    "memory_class,expected",
    [
        (" 4GB（即将停售）", Status.PLANNED_FOR_RETIREMENT),
        (" 256GB（已停售）", Status.RETIRED),
        (" 4GB（通用型）", None),
    ],
)
def test_alicloud_rds_class_status_of_unconfirmed_absence(memory_class, expected):
    spec = {"MemoryClass": memory_class}
    assert _rds_class_status(spec, False, absence_confirmed=False) == expected


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


def test_alicloud_inventory_database_prices_keep_the_failed_regions():
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
    previous_price = {"region_id": "eu-west-1", "database_id": "pg.n2.2c.1m"}
    offers, specs, clients = _rds_patches(rds_offers)
    with (
        offers,
        specs,
        patch(
            "sc_crawler.vendors._alicloud._rds_clients",
            return_value={region_id: Mock() for region_id in rds_offers},
        ),
        patch("sc_crawler.vendors._alicloud._fetch_rds_price", return_value=None),
        patch(
            "sc_crawler.vendors._alicloud._previous_active_prices",
            return_value=[previous_price],
        ) as previous,
    ):
        prices = inventory_database_prices(vendor)
    assert previous.call_args.args[2] == {"eu-west-1"}
    assert previous_price in prices
    assert {price["region_id"] for price in prices} == {"eu-central-1", "eu-west-1"}


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
                        "DBInstanceClasses": [{"DBInstanceClass": c} for c in found]
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
        pytest.raises(_RdsPriceUnavailable),
    ):
        _fetch_rds_price(client, "r", "pg.x", "basic", "z", "17.0", "cloud_essd", 20)
    logger.warning.assert_called_once()

    # not sold: no price
    client.describe_price_with_options.side_effect = Exception("InvalidParameter")
    assert (
        _fetch_rds_price(client, "r", "pg.x", "basic", "z", "17.0", "cloud_essd", 20)
        is None
    )


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
            raise Exception("Connection reset")
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


def test_alicloud_previous_rows_keep_the_recently_observed_ones():
    from datetime import UTC, datetime, timedelta

    from sc_crawler.tables import DatabasePrice

    now = datetime.now(UTC)

    def row(database_id, days, tz=UTC):
        observed_at = (now - timedelta(days=days)).replace(tzinfo=tz)
        return Mock(
            observed_at=observed_at,
            _mapping={"database_id": database_id, "observed_at": observed_at},
        )

    vendor = Mock(vendor_id="alicloud")
    vendor.session.exec.return_value = [
        row("recent", 10),
        # naive timestamps of SQLite are in UTC
        row("naive", 29, tz=None),
        row("old", 31),
    ]
    rows = _previous_rows(vendor, DatabasePrice)
    assert [r["database_id"] for r in rows] == ["recent", "naive"]
    # the original observation time is kept
    assert rows[0]["observed_at"] == now - timedelta(days=10)
    assert _previous_rows(Mock(session=None), DatabasePrice) == []


def test_alicloud_inventory_server_prices_spot_keeps_the_previous_ones():
    from sc_crawler.table_fields import Allocation

    def ondemand(region_id, zone_id, server_id):
        return Mock(
            allocation=Allocation.ONDEMAND,
            status=Status.ACTIVE,
            region_id=region_id,
            zone_id=zone_id,
            server_id=server_id,
        )

    vendor = Mock(
        vendor_id="alicloud",
        server_prices=[
            ondemand("r1", "r1a", "ecs.sampled"),
            ondemand("r1", "r1a", "ecs.not-sampled"),
        ],
    )

    def previous(region_id, zone_id, server_id, price):
        return {
            "region_id": region_id,
            "zone_id": zone_id,
            "server_id": server_id,
            "price": price,
        }

    price = Mock()
    price.price_info.rules.rule = [Mock(description="Preemptible Instance discount")]
    price.price_info.price.detail_infos.detail_info = [
        Mock(resource="instanceType", trade_price=0.02)
    ]
    price.price_info.price.currency = "USD"
    with (
        patch("sc_crawler.vendors._alicloud._ecs_clients", return_value={"r1": Mock()}),
        patch(
            "sc_crawler.vendors._alicloud._get_instance_price",
            side_effect=lambda instance_type, **kwargs: (
                price if instance_type == "ecs.sampled" else None
            ),
        ),
        patch(
            "sc_crawler.vendors._alicloud._previous_rows",
            return_value=[
                # sampled again: replaced
                previous("r1", "r1a", "ecs.sampled", 0.01),
                # not sampled now: kept
                previous("r1", "r1a", "ecs.not-sampled", 0.03),
                # not sold on-demand anymore: dropped
                previous("r1", "r1a", "ecs.gone", 0.04),
            ],
        ),
    ):
        prices = inventory_server_prices_spot(vendor)
    assert {(p["server_id"], p["price"]) for p in prices} == {
        ("ecs.sampled", 0.02),
        ("ecs.not-sampled", 0.03),
    }


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


def test_alicloud_previous_active_prices_of_regions_and_ids():
    rows = [
        {"region_id": "r1", "database_id": "pg.a"},
        {"region_id": "r2", "database_id": "pg.a"},
        {"region_id": "r2", "database_id": "pg.b"},
        {"region_id": "r3", "database_id": "pg.a"},
    ]
    from sc_crawler.tables import DatabasePrice

    with patch(
        "sc_crawler.vendors._alicloud._previous_rows", return_value=rows
    ) as previous:
        kept = _previous_active_prices(
            Mock(), DatabasePrice, {"r1"}, ids={("r2", "pg.b")}
        )
    assert kept == [rows[0], rows[2]]
    assert _previous_active_prices(Mock(), DatabasePrice, set()) == []
    previous.assert_called_once()


def test_alicloud_inventory_databases_drops_classes_not_orderable_by_complete_availability():
    """Incomplete specs, but complete availability: not orderable anymore."""
    rds_specs = {"eu-central-1": None, "cn-nanjing": _RDS_SPECS["cn-nanjing"]}
    previous = [
        # orderable, without specs: kept
        _previous_database("pg.x4.large.2c"),
        # not orderable in any region: dropped
        _previous_database("pg.gone.2c"),
    ]
    vendor, rows = _inventory_rds_databases(rds_specs=rds_specs, previous=previous)
    assert "pg.x4.large.2c" in rows
    assert "pg.gone.2c" not in rows


def test_alicloud_expire_previous_rows_without_new_records():
    from sc_crawler.tables import ServerPrice

    vendor = Mock()
    vendor.server_prices = []
    _expire_previous_rows(vendor, ServerPrice)
    filters = vendor.set_table_rows_inactive.call_args.args
    assert filters[0] is ServerPrice
    # active and older than 30 days
    assert len(filters) == 3
    _expire_previous_rows(Mock(session=None), ServerPrice)
