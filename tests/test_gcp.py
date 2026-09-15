from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from sc_crawler.inspector import _standardize_gpu_family, _standardize_gpu_model
from sc_crawler.table_fields import Allocation, PriceUnit, StorageType
from sc_crawler.vendors._gcp import (
    _search_servers,
    _server_accelerators,
    _server_bundled_local_ssd_gib,
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
):
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
    skus = _a3_highgpu_4g_skus() + _a3_highgpu_4g_skus("Preemptible")
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
        bundled_local_ssds=SimpleNamespace(partition_count=32),
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
    assert row["storage_size"] == 32 * 375
    assert row["storage_type"] == StorageType.NVME_SSD
    assert row["storages"] == [{"storage_type": StorageType.NVME_SSD, "size": 32 * 375}]


def test_standardize_gpu_model_maps_nvidia_gb300():
    assert _standardize_gpu_model("nvidia-gb300") == "GB300"
    assert _standardize_gpu_family({"gpu_model": "GB300"}) == "Blackwell"
