"""Unit tests for the Oracle Cloud Infrastructure vendor module."""

from unittest.mock import Mock, patch

import pytest

pytest.importorskip("oci")

from sc_crawler.table_fields import (  # noqa: E402
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)
from sc_crawler.vendors import _oci  # noqa: E402
from sc_crawler.vendors._oci import (  # noqa: E402
    _config,
    _config_hourly_price,
    _parse_processor_description,
    _part_price,
    _shape_configs,
    _shape_family,
    _shape_series,
    _shape_servers,
    _vcpus_per_ocpu,
    _zone_id,
    inventory_database_prices,
    inventory_database_storage_prices,
    inventory_database_storages,
    inventory_databases,
    inventory_ipv4_prices,
    inventory_regions,
    inventory_server_prices,
    inventory_server_prices_spot,
    inventory_servers,
    inventory_storage_prices,
    inventory_storages,
    inventory_traffic_prices,
    inventory_zones,
)

AD = "Uocm:EU-FRANKFURT-1-AD-1"


def _flex_shape(name="VM.Standard.E5.Flex", **kwargs):
    """A flexible shape as returned by ListShapes (after `oci.util.to_dict`)."""
    return {
        "shape": name,
        "processor_description": "2.3 GHz AMD EPYC™ 9J14 (Genoa)",
        "ocpus": 1.0,
        "memory_in_gbs": 12.0,
        "networking_bandwidth_in_gbps": 1.0,
        "gpus": 0,
        "gpu_description": None,
        "local_disks": 0,
        "local_disks_total_size_in_gbs": None,
        "local_disk_description": None,
        "ocpu_options": {"min": 1.0, "max": 126.0, "max_per_numa_node": 94.0},
        "memory_options": {
            "min_in_g_bs": 1.0,
            "max_in_g_bs": 2098.0,
            "default_per_ocpu_in_g_bs": 12.0,
            "min_per_ocpu_in_gbs": 1.0,
            "max_per_ocpu_in_gbs": 64.0,
            "max_per_numa_node_in_gbs": 1049.0,
        },
        "networking_bandwidth_options": {
            "min_in_gbps": 1.0,
            "max_in_gbps": 40.0,
            "default_per_ocpu_in_gbps": 1.0,
        },
        "billing_type": "PAID",
        "is_flexible": True,
        **kwargs,
    }


def _fixed_shape(name, ocpus, memory, **kwargs):
    """A fixed shape as returned by ListShapes (after `oci.util.to_dict`)."""
    return {
        "shape": name,
        "processor_description": "2.0 GHz Intel® Xeon® Platinum 8167M (Skylake)",
        "ocpus": float(ocpus),
        "memory_in_gbs": float(memory),
        "networking_bandwidth_in_gbps": 4.1,
        "gpus": 0,
        "gpu_description": None,
        "local_disks": 0,
        "local_disks_total_size_in_gbs": None,
        "local_disk_description": None,
        "ocpu_options": None,
        "memory_options": None,
        "networking_bandwidth_options": None,
        "billing_type": "PAID",
        "is_flexible": False,
        **kwargs,
    }


A1_FLEX = _flex_shape(
    "VM.Standard.A1.Flex",
    processor_description="3.0 GHz Ampere® Altra™",
    ocpu_options={"min": 1.0, "max": 80.0, "max_per_numa_node": 80.0},
    memory_options={
        "min_in_g_bs": 1.0,
        "max_in_g_bs": 512.0,
        "default_per_ocpu_in_g_bs": 6.0,
        "min_per_ocpu_in_gbs": 1.0,
        "max_per_ocpu_in_gbs": 64.0,
        "max_per_numa_node_in_gbs": 512.0,
    },
    billing_type="LIMITED_FREE",
)
A2_FLEX = _flex_shape(
    "VM.Standard.A2.Flex",
    processor_description="3.0 GHz Ampere® AmpereOne™ (Siryn™)",
    ocpu_options={"min": 1.0, "max": 78.0, "max_per_numa_node": 78.0},
)
DENSE_IO_BM = _fixed_shape(
    "BM.DenseIO.E6.Ax.192",
    192,
    2304,
    processor_description="2.7 GHz AMD EPYC™ 9J45 (Turin)",
    networking_bandwidth_in_gbps=200.0,
    local_disks=12,
    local_disks_total_size_in_gbs=81600.0,
    local_disk_description="NVMe SSD Storage",
)
MICRO = _fixed_shape(
    "VM.Standard.E2.1.Micro",
    1,
    1,
    processor_description="2.0 GHz AMD EPYC™ 7551 (Naples)",
    billing_type="ALWAYS_FREE",
)


def _part(part_number, *prices):
    """A product of the public price list with flat or (value, min, max) prices."""
    return {
        "partNumber": part_number,
        "currencyCodeLocalizations": [
            {
                "currencyCode": "USD",
                "prices": [
                    (
                        {
                            "model": "PAY_AS_YOU_GO",
                            "value": price[0],
                            "rangeMin": price[1],
                            "rangeMax": price[2],
                        }
                        if isinstance(price, tuple)
                        else {"model": "PAY_AS_YOU_GO", "value": price}
                    )
                    for price in prices
                ],
            }
        ],
    }


INFINITY = 999999999999999
PRICE_LIST = [
    _part("B97384", 0.03),  # E5 OCPU
    _part("B97385", 0.002),  # E5 memory
    _part("B93297", (0, 0, 3000), (0.01, 3000, INFINITY)),  # A1 OCPU
    _part("B93298", (0, 0, 18000), (0.0015, 18000, INFINITY)),  # A1 memory
    _part("B109529", 0.014),  # A2 OCPU
    _part("B109530", 0.002),  # A2 memory
    _part("B88514", 0.0638),  # VM Standard X7 OCPU
    _part("B88513", 0.0638),  # BM Standard X7 OCPU
    _part("B112556", 0.0108),  # Dense I/O E6 Ax OCPU
    _part("B112557", 0.009),  # Dense I/O E6 Ax memory
    _part("B112558", 0.1433),  # Dense I/O E6 Ax NVMe
    _part("B95909", 2),  # GPU A10
    _part("B91961", 0.0255),  # block volume storage
    _part("B91962", 0.0017),  # block volume performance units
    _part("B88327", (0, 0, 10240), (0.0085, 10240, INFINITY)),  # egress NA/EU/UK
    _part("B93455", (0, 0, 10240), (0.025, 10240, INFINITY)),  # egress APAC/SA
    _part("B93456", (0, 0, 10240), (0.05, 10240, INFINITY)),  # egress MEA
]


@pytest.fixture(autouse=True)
def _clear_caches():
    """Reset the in-memory caches, so each test can patch the API helpers."""
    for cached in (_oci._price_parts, _oci._warn_no_price, _oci._warn_unknown):
        cached.cache_clear()
    _config.cache_clear()
    yield
    _oci._price_parts.cache_clear()
    _config.cache_clear()


@pytest.fixture
def price_list():
    with patch.object(_oci, "_get_price_list", return_value=PRICE_LIST):
        yield


def _vendor(shapes_by_ad=None):
    """A vendor with a zone for each key of the availability domain -> shapes dict."""
    vendor = Mock(vendor_id="oci")
    vendor.zones = [
        Mock(
            region_id="eu-frankfurt-1",
            zone_id=_zone_id("eu-frankfurt-1", ad),
            api_reference=ad,
            status=Status.ACTIVE,
        )
        for ad in (shapes_by_ad or {})
    ]
    return vendor


def _patch_shapes(shapes_by_ad):
    return patch.object(
        _oci, "_get_shapes", side_effect=lambda region, ad: shapes_by_ad[ad]
    )


def test_config_from_environment(monkeypatch):
    monkeypatch.setenv("OCI_USER_OCID", "ocid1.user.oc1..user")
    monkeypatch.setenv("OCI_TENANCY_OCID", "ocid1.tenancy.oc1..tenancy")
    monkeypatch.setenv("OCI_FINGERPRINT", "aa:bb")
    monkeypatch.setenv("OCI_REGION", "eu-frankfurt-1")
    monkeypatch.setenv("OCI_PRIVATE_KEY", "PEM")
    with patch.object(_oci.oci.config, "validate_config"):
        config = _config()
    assert config == {
        "user": "ocid1.user.oc1..user",
        "tenancy": "ocid1.tenancy.oc1..tenancy",
        "fingerprint": "aa:bb",
        "region": "eu-frankfurt-1",
        "key_content": "PEM",
    }


def test_config_requires_private_key(monkeypatch):
    monkeypatch.setenv("OCI_USER_OCID", "ocid1.user.oc1..user")
    monkeypatch.setenv("OCI_TENANCY_OCID", "ocid1.tenancy.oc1..tenancy")
    monkeypatch.setenv("OCI_FINGERPRINT", "aa:bb")
    monkeypatch.setenv("OCI_REGION", "eu-frankfurt-1")
    monkeypatch.delenv("OCI_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("OCI_PRIVATE_KEY_PATH", raising=False)
    with pytest.raises(KeyError, match="OCI_PRIVATE_KEY"):
        _config()


def test_config_falls_back_to_config_file(monkeypatch):
    monkeypatch.delenv("OCI_TENANCY_OCID", raising=False)
    monkeypatch.setenv("OCI_CONFIG_PROFILE", "CRAWLER")
    with patch.object(
        _oci.oci.config, "from_file", return_value={"region": "x"}
    ) as from_file:
        assert _config() == {"region": "x"}
    from_file.assert_called_once_with(profile_name="CRAWLER")


@pytest.mark.parametrize(
    "region,availability_domain,expected",
    [
        ("eu-frankfurt-1", "Uocm:EU-FRANKFURT-1-AD-2", "eu-frankfurt-1-ad-2"),
        ("us-phoenix-1", "Uocm:PHX-AD-1", "us-phoenix-1-ad-1"),
        ("us-ashburn-1", "Uocm:US-ASHBURN-AD-3", "us-ashburn-1-ad-3"),
    ],
)
def test_zone_id(region, availability_domain, expected):
    assert _zone_id(region, availability_domain) == expected


def test_zone_id_unknown_format():
    with pytest.raises(ValueError):
        _zone_id("eu-frankfurt-1", "Uocm:EU-FRANKFURT-1-FD")


@pytest.mark.parametrize(
    "shape_name,expected",
    [
        ("VM.Standard.E5.Flex", ("VM", "Standard.E5")),
        ("VM.Standard.E6.Ax.Flex", ("VM", "Standard.E6.Ax")),
        ("VM.Standard2.16", ("VM", "Standard2")),
        ("VM.Standard.E2.1.Micro", ("VM", "Standard.E2")),
        ("BM.Standard.A4.Ax.48", ("BM", "Standard.A4.Ax")),
        ("BM.GPU.A100-v2.8", ("BM", "GPU.A100-v2")),
        ("VM.GPU.A10.2", ("VM", "GPU.A10")),
        ("BM.GPU4.8", ("BM", "GPU4")),
        ("VM.DenseIO.E5.Flex", ("VM", "DenseIO.E5")),
        ("BM.Optimized3.36", ("BM", "Optimized3")),
    ],
)
def test_shape_series(shape_name, expected):
    assert _shape_series(shape_name) == expected


def test_shape_series_unknown_format():
    with pytest.raises(ValueError, match="Unknown OCI shape name"):
        _shape_series("DVH.Standard2.52")


@pytest.mark.parametrize(
    "series,expected",
    [
        ("Standard.E5", "Standard"),
        ("Standard2", "Standard"),
        ("DenseIO.E6.Ax", "Dense I/O"),
        ("DenseIO2", "Dense I/O"),
        ("GPU.A10", "GPU"),
        ("GPU4", "GPU"),
        ("Optimized3", "Optimized"),
        ("HPC2", "HPC"),
        ("Quantum1", None),
    ],
)
def test_shape_family(series, expected):
    assert _shape_family(series) == expected


@pytest.mark.parametrize(
    "description,expected",
    [
        ("2.3 GHz AMD EPYC™ 9J14 (Genoa)", (2.3, "AMD", "EPYC", "9J14")),
        ("3.0 GHz Intel® Xeon® Gold 6354 (Ice Lake)", (3.0, "Intel", "Xeon", "6354")),
        (
            "2.0 GHz Intel® Xeon® Platinum 8167M (Skylake)",
            (2.0, "Intel", "Xeon", "8167M"),
        ),
        (
            "2.3 GHz Intel® Xeon® E5-2699 v3 (Haswell)",
            (2.3, "Intel", "Xeon", "E5-2699 v3"),
        ),
        (
            "2.2 GHz Base 3.9 GHz Turbo Intel® Xeon® Platinum 6987C-P (Granite Rapids)",
            (2.2, "Intel", "Xeon", "6987C-P"),
        ),
        ("3.0 GHz Ampere® Altra™", (3.0, "Ampere", "Altra", None)),
        ("3.0 GHz Ampere® AmpereOne™ (Siryn™)", (3.0, "Ampere", "AmpereOne", None)),
        (
            "3.6 GHz Ampere® AmpereOne-M™ (Banshee 12™)",
            (3.6, "Ampere", "AmpereOne-M", None),
        ),
        ("AmpereOne-M", (None, "Ampere", "AmpereOne-M", None)),
        (None, (None, None, None, None)),
    ],
)
def test_parse_processor_description(description, expected):
    cpu = _parse_processor_description(description)
    assert (
        cpu["cpu_speed"],
        cpu["cpu_manufacturer"],
        cpu["cpu_family"],
        cpu["cpu_model"],
    ) == expected


def test_vcpus_per_ocpu():
    assert _vcpus_per_ocpu(_flex_shape()) == 2
    assert _vcpus_per_ocpu(A1_FLEX) == 1
    assert _vcpus_per_ocpu(A2_FLEX) == 2
    a4_ax = _flex_shape("VM.Standard.A4.Ax.Flex", processor_description="AmpereOne-M")
    assert _vcpus_per_ocpu(a4_ax) == 2
    # Arm shape without a processor description
    assert (
        _vcpus_per_ocpu(
            _flex_shape("VM.Standard.A1.Flex", **{"processor_description": None})
        )
        == 1
    )
    with pytest.raises(ValueError, match="Unknown OCPU definition"):
        _vcpus_per_ocpu(
            _flex_shape("VM.Standard.A9.Flex", processor_description="Ampere Next")
        )


def test_shape_configs_fixed():
    configs = _shape_configs(_fixed_shape("VM.Standard2.4", 4, 60))
    assert configs == [
        {
            "server_id": "VM.Standard2.4",
            "ocpus": 4.0,
            "memory_gb": 60.0,
            "local_disks": 0,
            "local_disks_gb": 0,
            "network_speed": 4.1,
            "extended_memory": False,
        }
    ]


def test_shape_configs_flex_grid():
    configs = {config["server_id"]: config for config in _shape_configs(_flex_shape())}
    # 1-64 OCPUs and the max of the shape, with 2/4/8 GiB memory per vCPU
    assert len(configs) == 8 * 3
    assert {config["ocpus"] for config in configs.values()} == {
        1,
        2,
        4,
        8,
        16,
        32,
        64,
        126,
    }
    config = configs["VM.Standard.E5.Flex.4-32"]
    assert (config["ocpus"], config["memory_gb"]) == (4, 32)
    assert config["network_speed"] == 4
    assert not config["extended_memory"]
    # network bandwidth is capped at the max of the shape
    assert configs["VM.Standard.E5.Flex.64-512"]["network_speed"] == 40
    # more OCPUs or memory than available on a NUMA node
    assert configs["VM.Standard.E5.Flex.126-504"]["extended_memory"]
    assert not configs["VM.Standard.E5.Flex.64-1024"]["extended_memory"]


def test_shape_configs_flex_limits():
    shape = _flex_shape(
        "VM.Optimized3.Flex",
        ocpu_options={"min": 1.0, "max": 18.0, "max_per_numa_node": None},
        memory_options={
            "min_in_g_bs": 1.0,
            "max_in_g_bs": 256.0,
            "default_per_ocpu_in_g_bs": 14.0,
            "min_per_ocpu_in_gbs": 1.0,
            "max_per_ocpu_in_gbs": 64.0,
            "max_per_numa_node_in_gbs": None,
        },
    )
    server_ids = [config["server_id"] for config in _shape_configs(shape)]
    assert "VM.Optimized3.Flex.16-256" in server_ids
    assert "VM.Optimized3.Flex.18-144" in server_ids
    # 18 OCPUs with 8 GiB per vCPU is over the 256 GB max memory of the shape
    assert "VM.Optimized3.Flex.18-288" not in server_ids
    assert "VM.Optimized3.Flex.32-128" not in server_ids


def test_shape_configs_flex_arm():
    a1 = [config["server_id"] for config in _shape_configs(A1_FLEX)]
    # 1 OCPU is 1 vCPU on A1, and 2 vCPUs on A2
    assert a1[:3] == [
        "VM.Standard.A1.Flex.1-2",
        "VM.Standard.A1.Flex.1-4",
        "VM.Standard.A1.Flex.1-8",
    ]
    a2 = [config["server_id"] for config in _shape_configs(A2_FLEX)]
    assert a2[:3] == [
        "VM.Standard.A2.Flex.1-4",
        "VM.Standard.A2.Flex.1-8",
        "VM.Standard.A2.Flex.1-16",
    ]


def test_shape_configs_dense_io_flex():
    shape = _flex_shape(
        "VM.DenseIO.E5.Flex",
        local_disks=1,
        local_disks_total_size_in_gbs=6800.0,
        local_disk_description="NVMe SSD Storage",
    )
    configs = _shape_configs(shape)
    assert [config["server_id"] for config in configs] == [
        "VM.DenseIO.E5.Flex.8-96",
        "VM.DenseIO.E5.Flex.16-192",
        "VM.DenseIO.E5.Flex.24-288",
        "VM.DenseIO.E5.Flex.32-384",
        "VM.DenseIO.E5.Flex.40-480",
        "VM.DenseIO.E5.Flex.48-576",
    ]
    assert [config["local_disks"] for config in configs] == [1, 2, 3, 4, 5, 6]
    assert configs[-1]["local_disks_gb"] == 40800
    # unknown flexible shapes with local disks are not guessed
    shape["shape"] = "VM.DenseIO.E9.Flex"
    with pytest.raises(ValueError, match="Unknown local disk configurations"):
        _shape_configs(shape)


def test_shape_servers_flex():
    vendor = Mock(vendor_id="oci")
    servers = {s["server_id"]: s for s in _shape_servers(_flex_shape(), vendor)}
    server = servers["VM.Standard.E5.Flex.4-32"]
    assert server["api_reference"] == "VM.Standard.E5.Flex"
    assert server["api_reference_object"] == {
        "shape": "VM.Standard.E5.Flex",
        "shape_config": {"ocpus": 4, "memory_in_gbs": 32},
    }
    assert (server["family"], server["series"]) == ("Standard", "Standard.E5")
    assert (server["vcpus"], server["cpu_cores"]) == (8, 4)
    assert server["cpu_architecture"] == CpuArchitecture.X86_64
    assert server["cpu_allocation"] == CpuAllocation.DEDICATED
    assert server["cpu_manufacturer"] == "AMD"
    assert server["memory_amount"] == 32 * 1024
    assert server["storage_size"] == 0
    assert server["storage_type"] is None
    assert server["accelerator_count"] == 0
    assert server["accelerator_type"] is None
    assert server["network_speed_max"] == 4
    assert server["description"] == "Standard (8 vCPUs, 32 GiB RAM)"
    assert server["compatible_storage_ids"] == [
        "lower-cost",
        "balanced",
        "higher-performance",
        "ultra-high-performance",
    ]
    assert server["status"] == Status.ACTIVE


def test_shape_servers_arm_cores():
    vendor = Mock(vendor_id="oci")
    a1 = {s["server_id"]: s for s in _shape_servers(A1_FLEX, vendor)}
    a2 = {s["server_id"]: s for s in _shape_servers(A2_FLEX, vendor)}
    server = a1["VM.Standard.A1.Flex.4-16"]
    assert (server["vcpus"], server["cpu_cores"]) == (4, 4)
    assert server["cpu_architecture"] == CpuArchitecture.ARM64
    assert server["cpu_family"] == "Altra"
    server = a2["VM.Standard.A2.Flex.4-32"]
    assert (server["vcpus"], server["cpu_cores"]) == (8, 8)
    assert server["cpu_family"] == "AmpereOne"


def test_shape_servers_bare_metal_dense_io():
    (server,) = _shape_servers(DENSE_IO_BM, Mock(vendor_id="oci"))
    assert server["server_id"] == "BM.DenseIO.E6.Ax.192"
    assert server["api_reference_object"] == {"shape": "BM.DenseIO.E6.Ax.192"}
    assert (server["family"], server["series"]) == ("Dense I/O", "DenseIO.E6.Ax")
    assert (server["vcpus"], server["cpu_cores"]) == (384, 192)
    assert server["storage_size"] == 81600
    assert server["storage_type"] == StorageType.NVME_SSD
    assert len(server["storages"]) == 12
    assert server["storages"][0].size == 6800
    assert server["description"] == (
        "Bare Metal Dense I/O (384 vCPUs, 2304 GiB RAM, 81600 GB NVMe)"
    )


def test_shape_servers_gpu():
    shape = _fixed_shape(
        "VM.GPU.A10.2",
        30,
        480,
        gpus=2,
        gpu_description="NVIDIA® A10",
        processor_description="2.6 GHz Intel® Xeon® Platinum 8358 (Ice Lake)",
    )
    (server,) = _shape_servers(shape, Mock(vendor_id="oci"))
    assert server["accelerator_count"] == 2
    assert server["accelerator_manufacturer"] == "NVIDIA"
    assert server["accelerator_model"] == "A10"
    assert server["accelerator_family"] == "Ampere"
    assert server["accelerator_memory_min"] == 24 * 1024
    assert server["accelerator_memory_total"] == 48 * 1024
    assert server["description"] == "GPU (60 vCPUs, 480 GiB RAM, 2xA10 24 GiB VRAM)"

    amd = _fixed_shape("BM.GPU.MI300X.8", 112, 2048, gpus=8)
    (server,) = _shape_servers(amd, Mock(vendor_id="oci"))
    assert server["accelerator_manufacturer"] == "AMD"
    assert server["accelerator_memory_total"] == 8 * 192 * 1024


def test_shape_servers_unknown_gpu_series():
    shape = _fixed_shape(
        "BM.GPU.X999.8", 64, 1024, gpus=8, gpu_description="NVIDIA® X999"
    )
    with patch.object(_oci.logger, "warning") as warning:
        (server,) = _shape_servers(shape, Mock(vendor_id="oci"))
    warning.assert_called_once()
    assert server["accelerator_count"] == 8
    assert server["accelerator_manufacturer"] == "NVIDIA"
    assert server["accelerator_model"] is None
    assert server["accelerator_memory_min"] is None


def test_shape_servers_always_free_is_inactive():
    (server,) = _shape_servers(MICRO, Mock(vendor_id="oci"))
    assert server["status"] == Status.INACTIVE
    assert server["cpu_allocation"] == CpuAllocation.BURSTABLE


def test_inventory_regions_status_from_subscriptions():
    vendor = Mock(vendor_id="oci")
    with (
        patch.object(
            _oci,
            "_get_regions",
            return_value=[
                {"key": "FRA", "name": "eu-frankfurt-1"},
                {"key": "PHX", "name": "us-phoenix-1"},
                {"key": "NRT", "name": "ap-tokyo-1"},
            ],
        ),
        patch.object(
            _oci,
            "_get_region_subscriptions",
            return_value=[
                {"region_name": "eu-frankfurt-1", "status": "READY"},
                {"region_name": "us-phoenix-1", "status": "IN_PROGRESS"},
            ],
        ),
    ):
        rows = {row["region_id"]: row for row in inventory_regions(vendor)}
    region = rows["eu-frankfurt-1"]
    assert region["status"] == Status.ACTIVE
    assert region["name"] == "Germany Central (Frankfurt)"
    assert region["aliases"] == ["FRA"]
    assert region["country_id"] == "DE"
    assert rows["us-phoenix-1"]["status"] == Status.INACTIVE
    assert rows["ap-tokyo-1"]["status"] == Status.INACTIVE


def test_inventory_regions_unknown_region_raises(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    with (
        patch.object(
            _oci, "_get_regions", return_value=[{"key": "XXX", "name": "xx-new-1"}]
        ),
        patch.object(_oci, "_get_region_subscriptions", return_value=[]),
    ):
        with pytest.raises(KeyError, match="xx-new-1"):
            inventory_regions(Mock(vendor_id="oci"))


def test_inventory_zones_only_in_active_regions():
    vendor = Mock(vendor_id="oci")
    vendor.regions = [
        Mock(
            region_id="us-phoenix-1",
            api_reference="us-phoenix-1",
            status=Status.ACTIVE,
        ),
        Mock(
            region_id="ap-tokyo-1", api_reference="ap-tokyo-1", status=Status.INACTIVE
        ),
    ]
    with patch.object(
        _oci,
        "_get_availability_domains",
        return_value=["Uocm:PHX-AD-1", "Uocm:PHX-AD-2"],
    ) as get_availability_domains:
        rows = inventory_zones(vendor)
    get_availability_domains.assert_called_once_with("us-phoenix-1")
    assert [row["zone_id"] for row in rows] == [
        "us-phoenix-1-ad-1",
        "us-phoenix-1-ad-2",
    ]
    assert rows[0]["api_reference"] == "Uocm:PHX-AD-1"
    assert rows[0]["name"] == "PHX-AD-1"
    assert rows[0]["region_id"] == "us-phoenix-1"


def test_inventory_servers_dedupes_shapes_of_zones():
    shapes_by_ad = {
        "Uocm:EU-FRANKFURT-1-AD-1": [_fixed_shape("VM.Standard2.4", 4, 60), MICRO],
        "Uocm:EU-FRANKFURT-1-AD-2": [
            _fixed_shape("VM.Standard2.4", 4, 60),
            DENSE_IO_BM,
        ],
    }
    vendor = _vendor(shapes_by_ad)
    with _patch_shapes(shapes_by_ad):
        rows = inventory_servers(vendor)
    assert sorted(row["server_id"] for row in rows) == [
        "BM.DenseIO.E6.Ax.192",
        "VM.Standard.E2.1.Micro",
        "VM.Standard2.4",
    ]
    assert all(row["vendor_id"] == "oci" for row in rows)


def test_part_price_ignores_free_tier(price_list):
    assert _part_price("B97384") == 0.03
    assert _part_price("B93297") == 0.01
    with pytest.raises(KeyError):
        _part_price("B00000")


def test_config_hourly_price(price_list):
    def price(shape, server_id=None):
        configs = {c["server_id"]: c for c in _shape_configs(shape)}
        return _config_hourly_price(shape, configs[server_id or shape["shape"]])

    # OCPU and memory parts
    e5 = price(_flex_shape(), "VM.Standard.E5.Flex.4-32")
    assert e5 == pytest.approx(4 * 0.03 + 32 * 0.002)
    # paid rate of the free tier
    assert price(A1_FLEX, "VM.Standard.A1.Flex.4-16") == pytest.approx(
        4 * 0.01 + 16 * 0.0015
    )
    # memory is included in the OCPU price, VM and BM parts differ
    assert price(_fixed_shape("VM.Standard2.4", 4, 60)) == pytest.approx(4 * 0.0638)
    assert price(_fixed_shape("BM.Standard2.52", 52, 768)) == pytest.approx(52 * 0.0638)
    # OCPU, memory and NVMe (TB) parts
    assert price(DENSE_IO_BM) == pytest.approx(
        192 * 0.0108 + 2304 * 0.009 + 81.6 * 0.1433
    )
    # per GPU, including the OCPUs and memory
    assert price(_fixed_shape("VM.GPU.A10.2", 30, 480, gpus=2)) == 4


def test_config_hourly_price_unknown_series(price_list):
    shape = _fixed_shape("BM.DenseIO.A4.Ax.72", 72, 1152)
    with patch.object(_oci.logger, "warning") as warning:
        assert _config_hourly_price(shape, _shape_configs(shape)[0]) is None
        assert _config_hourly_price(shape, _shape_configs(shape)[0]) is None
    # warned only once per shape
    warning.assert_called_once()


def test_inventory_server_prices(price_list):
    shapes_by_ad = {
        "Uocm:EU-FRANKFURT-1-AD-1": [
            _fixed_shape("VM.Standard2.4", 4, 60),
            MICRO,
            _fixed_shape("BM.DenseIO.A4.Ax.72", 72, 1152),
        ],
        "Uocm:EU-FRANKFURT-1-AD-2": [_fixed_shape("VM.Standard2.4", 4, 60)],
    }
    with _patch_shapes(shapes_by_ad):
        rows = inventory_server_prices(_vendor(shapes_by_ad))
    # no price for the always free and the unknown shapes
    assert [(row["zone_id"], row["server_id"]) for row in rows] == [
        ("eu-frankfurt-1-ad-1", "VM.Standard2.4"),
        ("eu-frankfurt-1-ad-2", "VM.Standard2.4"),
    ]
    row = rows[0]
    assert row["region_id"] == "eu-frankfurt-1"
    assert row["allocation"] == Allocation.ONDEMAND
    assert row["unit"] == PriceUnit.HOUR
    assert row["price"] == pytest.approx(0.2552)
    assert row["currency"] == "USD"
    assert row["operating_system"] == "Linux"


def test_inventory_server_prices_skips_inactive_zones(price_list):
    shapes_by_ad = {AD: [_fixed_shape("VM.Standard2.4", 4, 60)]}
    vendor = _vendor(shapes_by_ad)
    vendor.zones[0].status = Status.INACTIVE
    with _patch_shapes(shapes_by_ad):
        assert inventory_server_prices(vendor) == []


def test_inventory_server_prices_spot(price_list):
    shapes_by_ad = {
        AD: [
            _flex_shape(),
            A2_FLEX,
            _fixed_shape("VM.Standard2.4", 4, 60),
            _fixed_shape("BM.Standard2.52", 52, 768),
            MICRO,
        ]
    }
    with _patch_shapes(shapes_by_ad):
        rows = inventory_server_prices_spot(_vendor(shapes_by_ad))
    by_id = {row["server_id"]: row for row in rows}
    assert all(row["allocation"] == Allocation.SPOT for row in rows)
    # 50% discount on the on-demand price
    assert by_id["VM.Standard.E5.Flex.4-32"]["price"] == pytest.approx(0.092)
    assert by_id["VM.Standard2.4"]["price"] == pytest.approx(0.1276)
    # no preemptible capacity for bare metal, A2, always free and extended
    # memory instances
    assert "BM.Standard2.52" not in by_id
    assert "VM.Standard.E2.1.Micro" not in by_id
    assert not any(server_id.startswith("VM.Standard.A2") for server_id in by_id)
    assert "VM.Standard.E5.Flex.64-512" in by_id
    assert "VM.Standard.E5.Flex.126-504" not in by_id


def test_inventory_storages_and_prices(price_list):
    vendor = Mock(vendor_id="oci")
    vendor.regions = [Mock(region_id="eu-frankfurt-1"), Mock(region_id="ap-tokyo-1")]
    storages = {row["storage_id"]: row for row in inventory_storages(vendor)}
    assert list(storages) == [
        "lower-cost",
        "balanced",
        "higher-performance",
        "ultra-high-performance",
    ]
    assert storages["balanced"]["max_iops"] == 25_000
    assert storages["balanced"]["max_throughput"] == 480
    assert storages["balanced"]["min_size"] == 50
    assert storages["balanced"]["max_size"] == 32768

    prices = inventory_storage_prices(vendor)
    assert len(prices) == 2 * 4
    by_id = {
        row["storage_id"]: row for row in prices if row["region_id"] == "ap-tokyo-1"
    }
    # storage price plus the performance units (VPU) per GB
    assert by_id["lower-cost"]["price"] == pytest.approx(0.0255)
    assert by_id["balanced"]["price"] == pytest.approx(0.0255 + 10 * 0.0017)
    assert by_id["higher-performance"]["price"] == pytest.approx(0.0595)
    assert by_id["ultra-high-performance"]["price"] == pytest.approx(0.0765)
    assert by_id["balanced"]["unit"] == PriceUnit.GB_MONTH


def test_inventory_traffic_prices(price_list):
    vendor = Mock(vendor_id="oci")
    vendor.regions = [
        Mock(region_id="eu-frankfurt-1"),
        Mock(region_id="sa-saopaulo-1"),
        Mock(region_id="il-jerusalem-1"),
    ]
    rows = inventory_traffic_prices(vendor)
    assert len(rows) == 6
    inbound = [row for row in rows if row["direction"] == TrafficDirection.IN]
    assert all(row["price"] == 0 and row["price_tiered"] == [] for row in inbound)
    outbound = {
        row["region_id"]: row
        for row in rows
        if row["direction"] == TrafficDirection.OUT
    }
    assert outbound["eu-frankfurt-1"]["price"] == 0.0085
    assert outbound["sa-saopaulo-1"]["price"] == 0.025
    assert outbound["il-jerusalem-1"]["price"] == 0.05
    # first 10 TB is free per month
    assert outbound["eu-frankfurt-1"]["price_tiered"] == [
        {"lower": 1, "upper": 10240, "price": 0},
        {"lower": 10241, "upper": "Infinity", "price": 0.0085},
    ]


def test_inventory_traffic_prices_unknown_region_group(price_list, monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    vendor = Mock(vendor_id="oci")
    vendor.regions = [Mock(region_id="xx-new-1")]
    with pytest.raises(KeyError):
        inventory_traffic_prices(vendor)


def test_inventory_ipv4_prices_are_free():
    vendor = Mock(vendor_id="oci")
    vendor.regions = [Mock(region_id="eu-frankfurt-1"), Mock(region_id="ap-tokyo-1")]
    rows = inventory_ipv4_prices(vendor)
    assert [(row["region_id"], row["price"]) for row in rows] == [
        ("eu-frankfurt-1", 0),
        ("ap-tokyo-1", 0),
    ]


def test_region_locations_cover_egress_parts():
    for region_id in _oci._REGION_LOCATIONS:
        assert region_id.split("-")[0] in _oci._EGRESS_PARTS


def test_database_inventories_are_not_implemented():
    vendor = Mock(vendor_id="oci")
    assert inventory_databases(vendor) == []
    assert inventory_database_prices(vendor) == []
    assert inventory_database_storages(vendor) == []
    assert inventory_database_storage_prices(vendor) == []
