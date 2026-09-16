from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from sc_crawler.inspector import _standardize_gpu_family, _standardize_gpu_model
from sc_crawler.table_fields import Allocation, PriceUnit, StorageType
from sc_crawler.utils import _GIB_TO_GB
from sc_crawler.vendors._gcp import (
    _local_ssd_partition_gib,
    _search_servers,
    _server_accelerators,
    _server_bundled_local_ssd_gib,
    _server_family,
    _skus_dict,
    inventory_server_prices,
    inventory_server_prices_spot,
)

# us-central1 rates, rounded to the catalog's units + nanos pairs
# https://cloud.google.com/products/compute/pricing/accelerator-optimized
A3_CORE = (0, 32_220_000)
A3_RAM = (0, 2_817_000)
H100 = (11, 60_000_000)
# Catalog Local SSD is GiB-month ($0.08); server prices convert with /730
# https://cloud.google.com/products/compute/pricing/storage-optimized
LOCAL_SSD_MONTHLY = (0, 80_000_000)
LOCAL_SSD_HOURLY = 0.08 / 730
A3_HIGHGPU_4G_LOCAL_SSD_GIB = 3000


def _sku(
    description: str,
    *,
    resource_group: str,
    regions: list[str],
    units: int,
    nanos: int,
    resource_family: str = "Compute",
    usage_type: str = "OnDemand",
    usage_unit: str | None = None,
):
    if usage_unit is None:
        usage_unit = {"RAM": "GiBy.h", "LocalSSD": "GiBy.mo"}.get(resource_group, "h")
    return SimpleNamespace(
        description=description,
        category=SimpleNamespace(
            resource_family=resource_family,
            resource_group=resource_group,
            usage_type=usage_type,
        ),
        service_regions=regions,
        pricing_info=[
            SimpleNamespace(
                pricing_expression=SimpleNamespace(
                    usage_unit=usage_unit,
                    tiered_rates=[
                        SimpleNamespace(
                            unit_price=SimpleNamespace(
                                units=units, nanos=nanos, currency_code="USD"
                            )
                        )
                    ],
                )
            )
        ],
    )


def _a3_highgpu_4g_skus(usage_type: str = "OnDemand"):
    spot = usage_type == "Preemptible"
    prefix = "Spot Preemptible " if spot else ""
    gpu_suffix = "attached to Spot Preemptible VMs running in" if spot else "running in"
    local_ssd_description = (
        "SSD backed Local Storage attached to Spot Preemptible VMs"
        if spot
        else "SSD backed Local Storage"
    )
    return [
        _sku(
            f"{prefix}A3 Instance Core running in Americas",
            resource_group="CPU",
            regions=["us-central1"],
            units=A3_CORE[0],
            nanos=A3_CORE[1],
            usage_type=usage_type,
        ),
        _sku(
            f"{prefix}A3 Instance Ram running in Americas",
            resource_group="RAM",
            regions=["us-central1"],
            units=A3_RAM[0],
            nanos=A3_RAM[1],
            usage_type=usage_type,
        ),
        _sku(
            f"Nvidia H100 80GB GPU {gpu_suffix} Americas",
            resource_group="GPU",
            regions=["us-central1"],
            units=H100[0],
            nanos=H100[1],
            usage_type=usage_type,
        ),
        _sku(
            local_ssd_description,
            # live Catalog uses LocalSSD (not the PD "SSD" group)
            resource_group="LocalSSD",
            resource_family="Storage",
            regions=["us-central1"],
            units=LOCAL_SSD_MONTHLY[0],
            nanos=LOCAL_SSD_MONTHLY[1],
            usage_type=usage_type,
        ),
    ]


def _gcp_accelerators(accelerators):
    """Patch the machineTypes name -> guestAcceleratorType lookup."""
    return patch(
        "sc_crawler.vendors._gcp._server_accelerators", return_value=accelerators
    )


def _gcp_bundled_local_ssd(sizes):
    """Patch server name -> bundled Local SSD GiB lookup."""
    return patch(
        "sc_crawler.vendors._gcp._server_bundled_local_ssd_gib", return_value=sizes
    )


def _gcp_vendor(*, servers):
    vendor = Mock(vendor_id="gcp")
    vendor.regions = [
        SimpleNamespace(
            name="us-central1",
            region_id="us-central1",
            zones=[SimpleNamespace(name="us-central1-a", zone_id="us-central1-a")],
        )
    ]
    vendor.servers = servers
    return vendor


def _a3_highgpu_4g(gpu_count=4):
    return SimpleNamespace(
        name="a3-highgpu-4g",
        server_id="a3-highgpu-4g",
        vcpus=104,
        memory_amount=936 * 1024,
        gpu_count=gpu_count,
        # standardized for cross-vendor comparison, see _standardize_gpu_model
        gpu_model="H100",
    )


@contextmanager
def _a3_price_patches(
    skus, *, accelerator="nvidia-h100-80gb", local_ssd_gib=A3_HIGHGPU_4G_LOCAL_SSD_GIB
):
    with ExitStack() as stack:
        stack.enter_context(patch("sc_crawler.vendors._gcp._skus", return_value=skus))
        stack.enter_context(
            patch("sc_crawler.vendors._gcp._server_in_zone", return_value=True)
        )
        stack.enter_context(_gcp_accelerators({"a3-highgpu-4g": accelerator}))
        stack.enter_context(
            _gcp_bundled_local_ssd(
                {"a3-highgpu-4g": local_ssd_gib} if local_ssd_gib else {}
            )
        )
        yield


@pytest.fixture(autouse=True)
def _clear_caches():
    _skus_dict.cache_clear()
    _server_accelerators.cache_clear()
    _server_bundled_local_ssd_gib.cache_clear()
    yield
    _skus_dict.cache_clear()
    _server_accelerators.cache_clear()
    _server_bundled_local_ssd_gib.cache_clear()


def test_gcp_skus_dict_indexes_gpu_skus():
    skus = [
        # newer GPU SKUs drop the Nvidia/Tesla prefix
        _sku(
            "H200 141GB GPU running in Netherlands",
            resource_group="GPU",
            regions=["europe-west4"],
            units=10,
            nanos=500_000_000,
        ),
        _sku(
            "Nvidia H100 80GB Mega GPU attached to Spot Preemptible VMs running in Tokyo",
            resource_group="GPU",
            regions=["asia-northeast1"],
            units=9,
            nanos=272_460_000,
            usage_type="Preemptible",
        ),
        _sku(
            "Nvidia H100 80GB Plus GPU running in Americas",
            resource_group="GPU",
            regions=["us-central1"],
            units=10,
            nanos=344_275_712,
        ),
        # G4 catalog name has no "GPU" token
        # https://cloud.google.com/skus/sku-groups/g4-on-demand-vms
        _sku(
            "RTX 6000 96GB running in Belgium",
            resource_group="GPU",
            regions=["europe-west1"],
            units=4,
            nanos=500_000_000,
        ),
        _sku(
            "RTX 6000 96GB attached to Spot Preemptible VMs running in Belgium",
            resource_group="GPU",
            regions=["europe-west1"],
            units=1,
            nanos=720_000_000,
            usage_type="Preemptible",
        ),
        # only Spot and OnDemand GPUs are priced
        _sku(
            "Nvidia Tesla T4 GPU attached to Sole Tenancy VMs running in Americas",
            resource_group="GPU",
            regions=["us-central1"],
            units=0,
            nanos=350_000_000,
        ),
        _sku(
            "Commitment v1: H200 141GB GPU running in Americas for 3 Years",
            resource_group="GPU",
            regions=["us-central1"],
            units=5,
            nanos=0,
            usage_type="Commit3Yr",
        ),
    ]
    with patch("sc_crawler.vendors._gcp._skus", return_value=skus):
        lookup = _skus_dict()

    assert lookup["gpu"]["nvidia-h200-141gb"]["europe-west4"]["ondemand"] == (
        pytest.approx(10.5),
        "USD",
    )
    assert lookup["gpu"]["nvidia-h100-mega-80gb"]["asia-northeast1"]["spot"] == (
        pytest.approx(9.27246),
        "USD",
    )
    assert lookup["gpu"]["nvidia-h100-mega-80gb"]["us-central1"]["ondemand"] == (
        pytest.approx(10.344275712),
        "USD",
    )
    assert lookup["gpu"]["nvidia-rtx-pro-6000"]["europe-west1"]["ondemand"] == (
        pytest.approx(4.5),
        "USD",
    )
    assert lookup["gpu"]["nvidia-rtx-pro-6000"]["europe-west1"]["spot"] == (
        pytest.approx(1.72),
        "USD",
    )
    assert "nvidia-tesla-t4" not in lookup["gpu"]


def test_gcp_skus_dict_indexes_local_ssd_spot_and_ondemand():
    skus = [
        *_a3_highgpu_4g_skus(),
        *_a3_highgpu_4g_skus("Preemptible"),
        _sku(
            "C4D Instance Local SSD running in Americas",
            resource_group="LocalSSD",
            regions=["us-central1"],
            units=0,
            nanos=160_000_000,
            usage_unit="GiBy.mo",
        ),
        _sku(
            "Spot Preemptible C4D Instance Local SSD running in Americas",
            resource_group="LocalSSD",
            regions=["us-central1"],
            units=0,
            nanos=65_000_000,
            usage_type="Preemptible",
            usage_unit="GiBy.mo",
        ),
    ]
    with patch("sc_crawler.vendors._gcp._skus", return_value=skus):
        lookup = _skus_dict()

    # Catalog keeps GiB-month; hourly conversion happens in inventory_server_prices
    assert lookup["storage"]["local-ssd"]["us-central1"]["ondemand"] == (
        pytest.approx(0.08),
        "USD",
    )
    assert lookup["storage"]["local-ssd"]["us-central1"]["spot"] == (
        pytest.approx(0.08),
        "USD",
    )
    assert lookup["local_ssd"]["c4d"]["us-central1"]["ondemand"] == (
        pytest.approx(0.16),
        "USD",
    )
    assert lookup["local_ssd"]["c4d"]["us-central1"]["spot"] == (
        pytest.approx(0.065),
        "USD",
    )


def test_gcp_inventory_server_prices_prefers_c4d_local_ssd_sku():
    server = SimpleNamespace(
        name="c4d-standard-8-lssd",
        server_id="c4d-standard-8-lssd",
        vcpus=8,
        memory_amount=31 * 1024,
        gpu_count=0,
        gpu_model=None,
    )
    skus = [
        _sku(
            "C4D Instance Core running in Americas",
            resource_group="CPU",
            regions=["us-central1"],
            units=0,
            nanos=32_703_500,
        ),
        _sku(
            "C4D Instance Ram running in Americas",
            resource_group="RAM",
            regions=["us-central1"],
            units=0,
            nanos=3_495_578,
            usage_unit="GBy.h",
        ),
        _sku(
            "C4D Instance Local SSD running in Americas",
            resource_group="LocalSSD",
            regions=["us-central1"],
            units=0,
            nanos=160_000_000,
            usage_unit="GiBy.mo",
        ),
        _sku(
            "SSD backed Local Storage",
            resource_group="LocalSSD",
            resource_family="Storage",
            regions=["us-central1"],
            units=0,
            nanos=80_000_000,
            usage_unit="GiBy.mo",
        ),
    ]
    vendor = _gcp_vendor(servers=[server])
    with (
        patch("sc_crawler.vendors._gcp._skus", return_value=skus),
        patch("sc_crawler.vendors._gcp._server_in_zone", return_value=True),
        _gcp_accelerators({}),
        _gcp_bundled_local_ssd({"c4d-standard-8-lssd": 375}),
    ):
        prices = inventory_server_prices(vendor)

    expected = 8 * 0.0327035 + 31 * _GIB_TO_GB * 0.003495578 + 375 * 0.16 / 730
    assert len(prices) == 1
    assert prices[0]["price"] == pytest.approx(expected)


def test_gcp_skus_dict_price_includes_whole_units():
    """The per GPU hourly rates have a non-zero whole-dollar part."""
    with patch("sc_crawler.vendors._gcp._skus", return_value=_a3_highgpu_4g_skus()):
        lookup = _skus_dict()

    price, _ = lookup["gpu"]["nvidia-h100-80gb"]["us-central1"]["ondemand"]
    assert price == pytest.approx(11.06)


def test_gcp_inventory_server_prices_includes_gpus_and_bundled_local_ssd():
    vendor = _gcp_vendor(servers=[_a3_highgpu_4g()])
    with _a3_price_patches(_a3_highgpu_4g_skus()):
        prices = inventory_server_prices(vendor)

    cpu_and_ram = 0.03222 * 104 + 0.002817 * 936
    gpus = 11.06 * 4
    local_ssd = LOCAL_SSD_HOURLY * A3_HIGHGPU_4G_LOCAL_SSD_GIB
    assert len(prices) == 1
    assert prices[0]["price"] == pytest.approx(cpu_and_ram + gpus + local_ssd)
    assert prices[0]["allocation"] == Allocation.ONDEMAND
    assert prices[0]["unit"] == PriceUnit.HOUR
    # the 4 H100s dominate the bill
    assert prices[0]["price"] > 5 * cpu_and_ram


def test_gcp_inventory_server_prices_spot_includes_gpus_and_bundled_local_ssd():
    vendor = _gcp_vendor(servers=[_a3_highgpu_4g()])
    with _a3_price_patches(_a3_highgpu_4g_skus("Preemptible")):
        prices = inventory_server_prices_spot(vendor)

    assert len(prices) == 1
    assert prices[0]["allocation"] == Allocation.SPOT
    assert prices[0]["price"] == pytest.approx(
        0.03222 * 104
        + 0.002817 * 936
        + 11.06 * 4
        + LOCAL_SSD_HOURLY * A3_HIGHGPU_4G_LOCAL_SSD_GIB
    )
    # Local SSD must not be applied as a raw GiB-month rate (that made Spot ≫ OnDemand)
    assert prices[0]["price"] < 0.08 * A3_HIGHGPU_4G_LOCAL_SSD_GIB


def test_gcp_inventory_server_prices_keys_gpu_skus_on_accelerator_type():
    """Server.gpu_model is standardized ("H100"), so it cannot key the SKU lookup."""
    vendor = _gcp_vendor(servers=[_a3_highgpu_4g()])
    with _a3_price_patches(_a3_highgpu_4g_skus()):
        prices = inventory_server_prices(vendor)

    assert vendor.servers[0].gpu_model not in _skus_dict()["gpu"]
    assert len(prices) == 1


def test_gcp_inventory_server_prices_skips_gpu_server_without_gpu_sku():
    """Publishing a CPU + RAM only price for a GPU machine understates the bill."""
    vendor = _gcp_vendor(servers=[_a3_highgpu_4g()])
    with _a3_price_patches(_a3_highgpu_4g_skus(), accelerator="nvidia-h200-141gb"):
        prices = inventory_server_prices(vendor)

    assert prices == []


def test_gcp_inventory_server_prices_without_gpus():
    vendor = _gcp_vendor(
        servers=[
            SimpleNamespace(
                name="n2-standard-8",
                server_id="n2-standard-8",
                vcpus=8,
                memory_amount=32 * 1024,
                gpu_count=0,
                gpu_model=None,
            )
        ]
    )
    skus = [
        _sku(
            "N2 Instance Core running in Americas",
            resource_group="CPU",
            regions=["us-central1"],
            units=0,
            nanos=31_611_000,
        ),
        _sku(
            "N2 Instance Ram running in Americas",
            resource_group="RAM",
            regions=["us-central1"],
            units=0,
            nanos=4_237_000,
        ),
    ]
    with (
        patch("sc_crawler.vendors._gcp._skus", return_value=skus),
        patch("sc_crawler.vendors._gcp._server_in_zone", return_value=True),
        _gcp_accelerators({}),
        _gcp_bundled_local_ssd({}),
    ):
        prices = inventory_server_prices(vendor)

    assert len(prices) == 1
    assert prices[0]["price"] == pytest.approx(0.031611 * 8 + 0.004237 * 32)


def test_gcp_search_servers_fills_gpu_and_bundled_local_ssd_fields():
    machine = SimpleNamespace(
        id=1724003,
        name="a4x-maxgpu-4g-metal",
        description="Accelerator Optimized: 4 NVIDIA GB300 GPU, 144 vCPUs, 960GB RAM",
        guest_cpus=144,
        is_shared_cpu=False,
        architecture="ARM64",
        memory_mb=960 * 1024,
        deprecated=SimpleNamespace(state=""),
        accelerators=[
            SimpleNamespace(
                guest_accelerator_type="nvidia-gb300",
                guest_accelerator_count=4,
            )
        ],
        bundled_local_ssds=SimpleNamespace(partition_count=4),
    )
    with patch("sc_crawler.vendors._gcp._servers", return_value=[machine]):
        rows = _search_servers("us-central1-a")

    row = rows[0]
    assert row["gpu_count"] == 4
    assert row["gpu_model"] == "GB300"
    assert row["gpu_manufacturer"] == "NVIDIA"
    assert row["gpu_family"] == "Blackwell"
    assert row["gpu_memory_min"] == 279 * 1024
    assert row["gpu_memory_total"] == 4 * 279 * 1024
    assert len(row["gpus"]) == 4
    assert row["gpus"][0] == {
        "manufacturer": "NVIDIA",
        "family": "Blackwell",
        "model": "GB300",
        "memory": 279 * 1024,
    }
    assert row["storage_size"] == round(4 * 3000 * 1024**3 / 1000**3)
    assert row["storage_type"] == StorageType.NVME_SSD
    assert row["storages"] == [
        {
            "storage_type": StorageType.NVME_SSD,
            "size": round(4 * 3000 * 1024**3 / 1000**3),
        }
    ]


@pytest.mark.parametrize(
    ("server_name", "expected"),
    [
        ("c4-standard-4-lssd", 375),
        ("c4-standard-288-lssd-metal", 3000),
        ("a4x-highgpu-4g", 3000),
        ("a4x-maxgpu-4g-metal", 3000),
        ("z3-highmem-8-highlssd", 3000),
        ("z3-highmem-192-highlssd-metal", 6000),
    ],
)
def test_gcp_local_ssd_partition_gib(server_name, expected):
    assert _local_ssd_partition_gib(server_name) == expected


def test_gcp_search_servers_parses_fractional_g4_vgpu():
    """MachineTypes API reports count=1 for G4 vGPU slices; fraction is in description."""
    machine = SimpleNamespace(
        id=999935024,
        name="g4-standard-6",
        description="Graphics Optimized: 1/8 NVIDIA RTX PRO 6000 GPU, 6 vCPUs, 22GB RAM",
        guest_cpus=6,
        is_shared_cpu=False,
        architecture="X86_64",
        memory_mb=22528,
        deprecated=SimpleNamespace(state=""),
        accelerators=[
            SimpleNamespace(
                guest_accelerator_type="nvidia-rtx-pro-6000",
                guest_accelerator_count=1,
            )
        ],
        bundled_local_ssds=None,
    )
    with patch("sc_crawler.vendors._gcp._servers", return_value=[machine]):
        row = _search_servers("us-east1-b")[0]

    assert row["gpu_count"] == 0.125
    assert row["gpu_model"] == "RTX Pro 6000"
    assert row["gpu_memory_min"] == 12 * 1024
    assert row["gpu_memory_total"] == 12 * 1024
    assert len(row["gpus"]) == 1
    assert row["gpus"][0]["memory"] == 12 * 1024


def _g4_server(name, vcpus, memory_gib, gpu_count):
    return SimpleNamespace(
        name=name,
        server_id=name,
        vcpus=vcpus,
        memory_amount=memory_gib * 1024,
        gpu_count=gpu_count,
        gpu_model="RTX Pro 6000",
    )


# us-central1 rates
# https://cloud.google.com/skus/sku-groups/g4-on-demand-vms
G4_SKUS = [
    _sku(
        "G4 Instance Core running in Iowa",
        resource_group="CPU",
        regions=["us-central1"],
        units=0,
        nanos=48_910_000,
    ),
    _sku(
        "G4 Instance Ram running in Iowa",
        resource_group="RAM",
        regions=["us-central1"],
        units=0,
        nanos=5_870_000,
    ),
    _sku(
        "RTX 6000 96GB running in Iowa",
        resource_group="GPU",
        regions=["us-central1"],
        units=1,
        nanos=95_650_000,
    ),
    # covers vCPUs, memory and the GPU slice of a g4-standard-6
    _sku(
        "1/8 vGPU no lssd running in Iowa",
        resource_group="GPU",
        regions=["us-central1"],
        units=0,
        nanos=646_880_000,
    ),
    _sku(
        "1/8 vGPU no lssd attached to DWS Defined Duration VMs running in Iowa",
        resource_group="GPU",
        regions=["us-central1"],
        units=0,
        nanos=323_440_000,
    ),
]


@pytest.mark.parametrize(
    ("server", "expected"),
    [
        (_g4_server("g4-standard-6", 6, 22, 0.125), 0.646880),
        (_g4_server("g4-standard-12", 12, 45, 0.25), 1.293760),
        (_g4_server("g4-standard-24", 24, 90, 0.5), 2.587520),
        # whole GPU shapes keep the Core + Ram + GPU composition
        (_g4_server("g4-standard-48", 48, 180, 1.0), 4.499930),
    ],
)
def test_gcp_inventory_server_prices_fractional_gpu_uses_slice_sku(server, expected):
    """Google does not price fractional G4 shapes by scaling the whole GPU SKU."""
    vendor = _gcp_vendor(servers=[server])
    with (
        patch("sc_crawler.vendors._gcp._skus", return_value=G4_SKUS),
        patch("sc_crawler.vendors._gcp._server_in_zone", return_value=True),
        _gcp_accelerators({server.name: "nvidia-rtx-pro-6000"}),
        _gcp_bundled_local_ssd({}),
    ):
        prices = inventory_server_prices(vendor)

    assert len(prices) == 1
    assert prices[0]["price"] == pytest.approx(expected)


def test_gcp_inventory_server_prices_a4_uses_spot_machine_slice_sku():
    server = SimpleNamespace(
        name="a4-highgpu-8g",
        server_id="a4-highgpu-8g",
        vcpus=224,
        memory_amount=3968 * 1024,
        gpu_count=8,
        gpu_model="B200",
    )
    skus = [
        _sku(
            "Spot Preemptible A4 Nvidia B200 (1 gpu slice) running in Americas",
            resource_group="GPU",
            regions=["us-central1"],
            units=4,
            nanos=954_200_000,
            # This live SKU is categorized as OnDemand despite its description.
            usage_type="OnDemand",
        )
    ]
    vendor = _gcp_vendor(servers=[server])
    with (
        patch("sc_crawler.vendors._gcp._skus", return_value=skus),
        patch("sc_crawler.vendors._gcp._server_in_zone", return_value=True),
        _gcp_accelerators({"a4-highgpu-8g": "nvidia-b200"}),
        _gcp_bundled_local_ssd({"a4-highgpu-8g": 12000}),
    ):
        ondemand_prices = inventory_server_prices(vendor)
        spot_prices = inventory_server_prices_spot(vendor)

    assert ondemand_prices == []
    assert len(spot_prices) == 1
    assert spot_prices[0]["price"] == pytest.approx(39.6336)


@pytest.mark.parametrize(
    ("server_name", "expected"),
    [
        ("n2d-standard-96", "n2d"),
        ("n1-megamem-96", "m1"),
        ("n1-ultramem-40", "m1"),
        ("n1-ultramem-160", "m1"),
        ("a3-highgpu-8g", "a3"),
        ("a3-megagpu-8g", "a3plus"),
        ("a3-ultragpu-8g", "a3ultra"),
        ("m4-ultramem-112", "m4"),
        ("m4-ultramem-224", "m4ultramem224"),
        ("m4n-ultramem-224", "m4nultramem224"),
    ],
)
def test_gcp_server_family(server_name, expected):
    assert _server_family(server_name) == expected


@pytest.mark.parametrize(
    ("description", "usage_unit", "nanos", "expected"),
    [
        ("C4 Instance Ram running in Americas", "GiBy.h", 3_938_000, 0.003938),
        # a few families are billed per decimal GB-hour
        (
            "C4D Instance Ram running in Americas",
            "GBy.h",
            3_495_578,
            0.003495578 * _GIB_TO_GB,
        ),
        (
            "M4Ultramem224 Instance Ram running in Americas",
            "GBy.h",
            5_675_880,
            0.00567588 * _GIB_TO_GB,
        ),
        # the space before "Instance" is missing in some descriptions
        (
            "M4NUltramem224Instance Ram running in Iowa",
            "GiBy.h",
            10_216_600,
            0.0102166,
        ),
    ],
)
def test_gcp_skus_dict_normalizes_ram_to_gib(description, usage_unit, nanos, expected):
    skus = [
        _sku(
            description,
            resource_group="RAM",
            regions=["us-central1"],
            units=0,
            nanos=nanos,
            usage_unit=usage_unit,
        )
    ]
    with patch("sc_crawler.vendors._gcp._skus", return_value=skus):
        lookup = _skus_dict()

    family = description.split(" ")[0].replace("Instance", "").lower()
    price, _ = lookup["ram"][family]["us-central1"]["ondemand"]
    assert price == pytest.approx(expected)


@pytest.mark.parametrize(
    (
        "server_name",
        "cpu_description",
        "cpu_nanos",
        "ram_description",
        "ram_nanos",
        "ram_unit",
        "expected",
    ),
    [
        (
            "m4-ultramem-224",
            "M4Ultramem224 Instance Core running in Americas",
            23_170_000,
            "M4Ultramem224 Instance Ram running in Americas",
            5_675_880,
            "GBy.h",
            41.464125836,
        ),
        (
            "m4n-ultramem-224",
            "M4NUltramem224 Instance Core running in Iowa",
            41_706_000,
            "M4NUltramem224Instance Ram running in Iowa",
            10_216_600,
            "GiBy.h",
            70.1513472,
        ),
    ],
)
def test_gcp_inventory_server_prices_uses_specialized_ultramem_skus(
    server_name,
    cpu_description,
    cpu_nanos,
    ram_description,
    ram_nanos,
    ram_unit,
    expected,
):
    server = SimpleNamespace(
        name=server_name,
        server_id=server_name,
        vcpus=224,
        memory_amount=5952 * 1024,
        gpu_count=0,
        gpu_model=None,
    )
    skus = [
        _sku(
            cpu_description,
            resource_group="CPU",
            regions=["us-central1"],
            units=0,
            nanos=cpu_nanos,
        ),
        _sku(
            ram_description,
            resource_group="RAM",
            regions=["us-central1"],
            units=0,
            nanos=ram_nanos,
            usage_unit=ram_unit,
        ),
    ]
    vendor = _gcp_vendor(servers=[server])
    with (
        patch("sc_crawler.vendors._gcp._skus", return_value=skus),
        patch("sc_crawler.vendors._gcp._server_in_zone", return_value=True),
        _gcp_accelerators({}),
        _gcp_bundled_local_ssd({}),
    ):
        prices = inventory_server_prices(vendor)

    assert len(prices) == 1
    assert prices[0]["price"] == pytest.approx(expected)


def test_gcp_search_servers_fills_tpu_fields():
    machine = SimpleNamespace(
        id=7001,
        name="ct5lp-hightpu-4t",
        description="112 vCPUs, 192 GB RAM, 4 Google TPUs",
        guest_cpus=112,
        is_shared_cpu=False,
        architecture="X86_64",
        memory_mb=192 * 1024,
        deprecated=SimpleNamespace(state=""),
        accelerators=[
            SimpleNamespace(guest_accelerator_type="ct5lp", guest_accelerator_count=4)
        ],
        bundled_local_ssds=None,
    )
    with patch("sc_crawler.vendors._gcp._servers", return_value=[machine]):
        rows = _search_servers("us-central1-a")

    row = rows[0]
    assert row["gpu_count"] == 4
    assert row["gpu_model"] == "v5e"
    assert row["gpu_manufacturer"] == "Google"
    assert row["gpu_family"] == "TPU"
    assert row["gpu_memory_min"] == 16 * 1024
    assert row["gpu_memory_total"] == 4 * 16 * 1024
    assert (
        row["gpus"]
        == [
            {
                "manufacturer": "Google",
                "family": "TPU",
                "model": "v5e",
                "memory": 16 * 1024,
            }
        ]
        * 4
    )


def test_standardize_gpu_model_maps_nvidia_gb300():
    assert _standardize_gpu_model("nvidia-gb300") == "GB300"
    assert _standardize_gpu_family({"gpu_model": "GB300"}) == "Blackwell"


@pytest.mark.parametrize(
    ("raw", "model", "family"),
    [
        ("ct5l", "v5e", "TPU"),
        ("ct5lp", "v5e", "TPU"),
        ("ct5p", "v5p", "TPU"),
        ("ct6e", "v6e", "TPU"),
        ("tpu7x", "v7x", "TPU"),
        ("TPU7x", "v7x", "TPU"),
        ("TPU v5e", "v5e", "TPU"),
        ("ct3", "v3", "TPU"),
        ("ct3p", "v3", "TPU"),
    ],
)
def test_standardize_gpu_model_and_family_maps_gcp_tpu(raw, model, family):
    assert _standardize_gpu_model(raw) == model
    assert _standardize_gpu_family({"gpu_model": _standardize_gpu_model(raw)}) == family
