from cachier import cachier
from requests import get

from ..inspector import _extract_manufacturer
from ..lookup import map_compliance_frameworks_to_vendor
from ..sentry import sentry_capture_or_raise
from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    PriceUnit,
    StorageType,
)

_REGION_LOCATIONS: dict[str, dict] = {
    "ams": {"lat": 52.3676, "lon": 4.9041},
    "atl": {"lat": 33.7490, "lon": -84.3880, "state": "Georgia"},
    "blr": {
        "lat": 12.9716,
        "lon": 77.5946,
        "state": "Karnataka",
        "founding_year": 2022,
    },
    "bom": {
        "lat": 19.0760,
        "lon": 72.8777,
        "state": "Maharashtra",
        "founding_year": 2022,
    },  # https://blogs.vultr.com/namaste-india-vultr-has-landed-in-mumbai
    "cdg": {"lat": 48.8566, "lon": 2.3522},
    "del": {"lat": 28.6139, "lon": 77.2090, "founding_year": 2022},
    "dfw": {"lat": 32.7767, "lon": -96.7970, "state": "Texas"},
    "ewr": {"lat": 40.7357, "lon": -74.1724, "state": "New Jersey"},
    "fra": {"lat": 50.1109, "lon": 8.6821},
    "hnl": {
        "lat": 21.3069,
        "lon": -157.8583,
        "state": "Hawaii",
        "founding_year": 2022,
    },  # https://blogs.vultr.com/aloha-from-hawaii-vultr-is-now-live-in-honolulu
    "icn": {
        "lat": 37.5665,
        "lon": 126.9780,
        "founding_year": 2020,
    },  # https://blogs.vultr.com/Deploy-Cloud-Servers-in-South-Korea
    "itm": {
        "lat": 34.6937,
        "lon": 135.5023,
        "founding_year": 2023,
    },  # https://blogs.vultr.com/new-cloud-data-center-location-osaka-japan
    "jnb": {"lat": -26.2041, "lon": 28.0473, "founding_year": 2022},
    "lax": {"lat": 34.0522, "lon": -118.2437, "state": "California"},
    "lhr": {
        "lat": 51.5074,
        "lon": -0.1278,
        "founding_year": 2018,
    },  # https://blogs.vultr.com/vultr-UK-location (London hub)
    "mad": {"lat": 40.4168, "lon": -3.7038, "founding_year": 2022},
    "man": {
        "lat": 53.4808,
        "lon": -2.2426,
        "founding_year": 2023,
    },  # https://blogs.vultr.com/vultr-UK-location
    "mel": {
        "lat": -37.8136,
        "lon": 144.9631,
        "state": "Victoria",
        "founding_year": 2022,
    },
    "mex": {
        "lat": 19.4326,
        "lon": -99.1332,
        "founding_year": 2021,
    },  # https://blogs.vultr.com/Diecinueve-Vultrs-19th-Cloud-Location-is-in-Mexico-City
    "mia": {"lat": 25.7617, "lon": -80.1918, "state": "Florida"},
    "mxp": {
        "lat": 45.4642,
        "lon": 9.1900,
        "founding_year": 2026,
    },  # https://blogs.vultr.com/milan-cloud-data-center-region
    "nrt": {"lat": 35.6762, "lon": 139.6503},
    "ord": {"lat": 41.8781, "lon": -87.6298, "state": "Illinois"},
    "sao": {
        "lat": -23.5505,
        "lon": -46.6333,
        "founding_year": 2021,
    },  # https://blogs.vultr.com/Ol-Brasil-Vultrs-20th-Cloud-Location-is-in-So-Paulo
    "scl": {"lat": -33.4489, "lon": -70.6693, "founding_year": 2023},
    "sea": {"lat": 47.6062, "lon": -122.3321, "state": "Washington"},
    "sgp": {
        "lat": 1.3521,
        "lon": 103.8198,
        "founding_year": 2016,
    },  # https://blogs.vultr.com/vultr-welcomes-singapore
    "sjc": {"lat": 37.3382, "lon": -121.8863, "state": "California"},
    "sto": {
        "lat": 59.3293,
        "lon": 18.0686,
        "founding_year": 2021,
    },  # https://blogs.vultr.com/Announcing-Our-New-Cloud-Computing-Location-in-Sweden
    "syd": {"lat": -33.8688, "lon": 151.2093, "state": "New South Wales"},
    "tlv": {
        "lat": 32.0853,
        "lon": 34.7818,
        "founding_year": 2023,
    },  # https://blogs.vultr.com/vultr-tel-aviv
    "waw": {"lat": 52.2297, "lon": 21.0122, "founding_year": 2022},
    "yto": {"lat": 43.6532, "lon": -79.3832, "state": "Ontario"},
}

# https://www.vultr.com/api/#tag/plans
_PLAN_TYPES: dict[str, str] = {
    "vc2": "Cloud Compute",
    "vhf": "High Frequency Compute",
    "vhp": "High Performance",
    "voc": "Optimized Cloud Compute",
    "vcg": "Cloud GPU",
    "vx1": "VX1 Cloud Compute",
    "vdm": "Dedicated Metal GPU",
    "vdc": "Dedicated Cloud",
    "SSD": "Bare Metal SSD",
    "NVMe": "Bare Metal NVMe",
}

# Vultr gpu_type → per-GPU VRAM (GiB) and architecture family.
# https://www.nvidia.com/en-us/data-center/ / https://www.amd.com/en/products/accelerators/instinct/
_GPU_TYPES: dict[str, dict[str, int | str]] = {
    "NVIDIA_A16": {"vram_gb": 16, "family": "Ampere"},
    "NVIDIA_A40": {"vram_gb": 48, "family": "Ampere"},
    "NVIDIA_L40S": {"vram_gb": 48, "family": "Ada Lovelace"},
    "NVIDIA_A100": {"vram_gb": 40, "family": "Ampere"},
    "NVIDIA_A100_SXM": {"vram_gb": 80, "family": "Ampere"},
    "NVIDIA_H100": {"vram_gb": 80, "family": "Hopper"},
    "NVIDIA_B200": {"vram_gb": 192, "family": "Blackwell"},
    "NVIDIA_GH200": {"vram_gb": 96, "family": "Grace Hopper"},
    "AMD_MI300X": {"vram_gb": 192, "family": "CDNA3"},
    "AMD_MI325X": {"vram_gb": 256, "family": "CDNA3"},
    "AMD_MI355X": {"vram_gb": 288, "family": "CDNA4"},
}

_DISK_TYPES: dict[str, StorageType] = {
    "SSD": StorageType.SSD,
    "HIGHFREQUENCY": StorageType.NVME_SSD,
    "AMDHIGHPERF": StorageType.NVME_SSD,
    "INTELHIGHPERF": StorageType.NVME_SSD,
    "DEDICATEDOPTIMIZED": StorageType.NVME_SSD,
    "CLOUDGPU": StorageType.NVME_SSD,
    "DEDICATEDMETAL": StorageType.NVME_SSD,
    "VX": StorageType.NETWORK,
    "NVMe": StorageType.NVME_SSD,
}


_CPU_MODEL_PREFIXES: tuple[str, ...] = (
    "EPYC ",
    "Grace ",
    "Platinum ",
    "Gold ",
    "E3-",
    "E-",
)


def _standardize_cpu_model(cpu_model: str | None) -> str | None:
    """Normalize Vultr plan cpu_model to the SKU (family is set separately)."""
    if not cpu_model:
        return None
    model = cpu_model.strip()
    if not model:
        return None
    while True:
        stripped = False
        for prefix in _CPU_MODEL_PREFIXES:
            if model.startswith(prefix):
                model = model[len(prefix) :].lstrip()
                stripped = True
                break
        if not stripped:
            break
    return model or None


def _extract_cpu_family(cpu_model: str | None) -> str | None:
    """Extract cpu_family from Vultr plan cpu_model strings.

    Bare-metal plans often omit the Xeon brand (e.g. ``Gold 6448H``, ``E-2386G``).
    """
    if not cpu_model:
        return None
    nl = cpu_model.strip().lower()
    if "epyc" in nl or "turin" in nl or "genoa" in nl:
        return "EPYC"
    if "grace" in nl or "neoverse" in nl:
        return "Grace"
    if nl.startswith(("e-", "e3-")) or nl.startswith(("gold ", "platinum ")):
        return "Xeon"
    return None


def _storage_type_from_plan(plan: dict) -> StorageType:
    """Resolve storage type from a /v2/plans or /v2/plans-metal plan object."""
    api_storage = plan.get("storage_type")
    if api_storage in ["local_and_block_storage", "local_storage"]:
        return StorageType.NVME_SSD
    if api_storage == "block_storage":
        return StorageType.NETWORK
    disk_type = plan.get("disk_type")
    if disk_type:
        return _DISK_TYPES.get(disk_type)
    return _DISK_TYPES.get(plan.get("type"))


@cachier(separate_files=True)
def _get_regions():
    response = get("https://api.vultr.com/v2/regions", params={"per_page": 500})
    return response.json()["regions"]


@cachier(separate_files=True)
def _get_plans():
    response = get("https://api.vultr.com/v2/plans", params={"per_page": 500})
    return response.json()["plans"]


@cachier(separate_files=True)
def _get_plans_metal():
    response = get("https://api.vultr.com/v2/plans-metal", params={"per_page": 500})
    return response.json()["plans_metal"]


def inventory_compliance_frameworks(vendor):
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id,
        [
            "hipaa",
            "soc2t2",
            "iso27001",
        ],
    )


def inventory_regions(vendor):
    """List all regions from Vultr API."""
    items = []
    regions = _get_regions()
    with sentry_capture_or_raise(vendor=vendor):
        for region in regions:
            location = _REGION_LOCATIONS.get(region["id"], {})
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region["id"],
                    "name": region["city"],
                    "api_reference": region["id"],
                    "display_name": f"{region['city']} ({region['country']})",
                    "aliases": [],
                    "country_id": region["country"],
                    "state": location.get("state"),
                    "city": region["city"],
                    "address_line": None,
                    "zip_code": None,
                    "lon": location.get("lon"),
                    "lat": location.get("lat"),
                    "founding_year": location.get("founding_year"),
                    "green_energy": location.get("green_energy"),
                }
            )
    return items


def inventory_zones(vendor):
    """List all regions as availability zones.

    There is no concept of having multiple availability zones withing
    a region (virtual datacenter) at Vultr, so creating 1-1
    dummy Zones reusing the Region id and name.

    """
    items = []
    for region in vendor.regions:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "zone_id": region.region_id,
                "name": region.name,
                "api_reference": region.name,
                "display_name": region.name,
            }
        )
    return items


def inventory_servers(vendor):
    """List all servers from Vultr API."""
    plans = _get_plans()
    plans_metal = _get_plans_metal()

    items = []
    for server in plans + plans_metal:
        # CPU
        cpu_model_raw = server.get("cpu_model", "")
        cpu_manufacturer = server.get("cpu_vendor") or server.get("cpu_manufacturer")
        cpu_family = _extract_cpu_family(cpu_model_raw)
        cpu_model = _standardize_cpu_model(cpu_model_raw)
        vcpus = server.get("vcpu_count")
        cpu_count = server.get("cpu_count")
        cpu_threads = server.get("cpu_threads", 0)
        cpu_allocation = CpuAllocation.SHARED if vcpus else CpuAllocation.DEDICATED
        cpu_architecture = (
            CpuArchitecture.ARM64 if cpu_family == "Grace" else CpuArchitecture.X86_64
        )
        cpu_speed_mhz = server.get("cpu_mhz")
        cpu_speed_ghz = cpu_speed_mhz / 1000 if cpu_speed_mhz else None

        # GPU
        gpu_brand = server.get("gpu_brand", "")
        gpu_type = server.get("gpu_type")
        gpu_manufacturer_from_type = gpu_type.split("_")[0] if gpu_type else ""
        gpu_manufacturer = _extract_manufacturer(gpu_brand) or _extract_manufacturer(
            gpu_manufacturer_from_type
        )
        gpu_profile = _GPU_TYPES.get(gpu_type, {})
        gpu_vram_gb = gpu_profile.get("vram_gb")
        gpu_family = gpu_profile.get("family")
        gpu_vram_total_gb = server.get("gpu_vram_gb", 0)
        gpu_memory_min = (
            min(gpu_vram_gb, gpu_vram_total_gb)
            if gpu_vram_gb and gpu_vram_total_gb
            else None
        )
        gpu_count = round(gpu_vram_total_gb / gpu_vram_gb, 4) if gpu_vram_gb else 0
        gpu_model = " ".join(gpu_type.split("_")[1:]) if gpu_type else None

        # Storage
        storage_size_per_disk = server.get("disk")
        storage_type = _storage_type_from_plan(server)
        storage_size = storage_size_per_disk * server.get("disk_count", 1)

        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "server_id": server["id"],
                "name": server["id"],
                "api_reference": server["id"],
                "display_name": server["id"],
                "description": None,
                "family": _PLAN_TYPES.get(server["type"]),
                "vcpus": vcpus or cpu_threads,
                "hypervisor": None,
                "cpu_allocation": cpu_allocation,
                "cpu_cores": vcpus or cpu_count,
                "cpu_speed": cpu_speed_ghz,
                "cpu_architecture": cpu_architecture,
                "cpu_manufacturer": cpu_manufacturer,
                "cpu_family": cpu_family,
                "cpu_model": cpu_model,
                "cpu_l1d_cache": None,
                "cpu_l1d_cache_total": None,
                "cpu_l1i_cache": None,
                "cpu_l1i_cache_total": None,
                "cpu_l2_cache": None,
                "cpu_l2_cache_total": None,
                "cpu_l3_cache": None,
                "cpu_l3_cache_total": None,
                "cpu_flags": [],
                "cpus": [],
                "memory_amount": server["ram"],
                "memory_generation": None,
                "memory_speed": None,
                "memory_ecc": None,
                "gpu_count": gpu_count,
                "gpu_memory_min": gpu_memory_min,
                "gpu_memory_total": gpu_vram_total_gb,
                "gpu_manufacturer": gpu_manufacturer,
                "gpu_family": gpu_family,
                "gpu_model": gpu_model,
                "gpus": [],
                "storage_size": storage_size,
                "storage_type": storage_type,
                "storages": [],
                "network_speed_baseline": None,
                "inbound_traffic": 0,
                "outbound_traffic": server.get("bandwidth", 0),
                "ipv4": 0,
            }
        )
    return items


def inventory_server_prices(vendor):
    plans = _get_plans()
    plans_metal = _get_plans_metal()

    items = []
    for server in plans + plans_metal:
        for region_id in server.get("locations", []):
            if server["deploy_ondemand"]:
                location_cost = server.get("location_cost", {})
                hourly_price = server.get("hourly_cost")
                monthly_price = server.get("monthly_cost")
                if location_cost.get(region_id):
                    hourly_price = location_cost[region_id].get("hourly_cost")
                    monthly_price = location_cost[region_id].get("monthly_cost")
                if hourly_price == 0:
                    price_tiered = []
                else:
                    monthly_cap = int(monthly_price / hourly_price)
                    price_tiered = [
                        {"lower": 0, "upper": monthly_cap, "price": hourly_price},
                        {"lower": monthly_cap + 1, "upper": "Infinity", "price": 0},
                    ]
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": region_id,
                        "zone_id": region_id,
                        "server_id": server["id"],
                        "operating_system": "Linux",
                        "allocation": Allocation.ONDEMAND,
                        "unit": PriceUnit.HOUR,
                        "price": hourly_price,
                        "price_upfront": 0,
                        "price_tiered": price_tiered,
                        "currency": "USD",
                    }
                )
    return items


def inventory_server_prices_spot(vendor):
    plans = _get_plans()
    plans_metal = _get_plans_metal()

    items = []
    for server in plans + plans_metal:
        for region_id in server.get("locations", []):
            if server["deploy_preemptible"]:
                location_cost = server.get("location_cost", {})
                hourly_price = server.get("hourly_cost_preemptible")
                monthly_price = server.get("monthly_cost_preemptible")
                if location_cost.get(region_id):
                    hourly_price = location_cost[region_id].get(
                        "hourly_cost_preemptible"
                    )
                    monthly_price = location_cost[region_id].get(
                        "monthly_cost_preemptible"
                    )
                if hourly_price == 0:
                    price_tiered = []
                else:
                    monthly_cap = int(monthly_price / hourly_price)
                    price_tiered = [
                        {"lower": 0, "upper": monthly_cap, "price": hourly_price},
                        {"lower": monthly_cap + 1, "upper": "Infinity", "price": 0},
                    ]
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": region_id,
                        "zone_id": region_id,
                        "server_id": server["id"],
                        "operating_system": "Linux",
                        "allocation": Allocation.SPOT,
                        "unit": PriceUnit.HOUR,
                        "price": hourly_price,
                        "price_upfront": 0,
                        "price_tiered": price_tiered,
                        "currency": "USD",
                    }
                )
    return items


def inventory_storages(vendor):
    items = []
    # for storage in []:
    #     items.append(
    #         {
    #             "storage_id": ,
    #             "vendor_id": vendor.vendor_id,
    #             "name": ,
    #             "description": None,
    #             "storage_type": StorageType....,
    #             "max_iops": None,
    #             "max_throughput": None,
    #             "min_size": None,
    #             "max_size": None,
    #         }
    #     )
    return items


def inventory_storage_prices(vendor):
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "region_id": ,
    #             "storage_id": ,
    #             "unit": PriceUnit.GB_MONTH,
    #             "price": ,
    #             "currency": "USD",
    #         }
    #     )
    return items


def inventory_traffic_prices(vendor):
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "region_id": ,
    #             "price": ,
    #             "price_tiered": [],
    #             "currency": "USD",
    #             "unit": PriceUnit.GB_MONTH,
    #             "direction": TrafficDirection....,
    #         }
    #     )
    return items


def inventory_ipv4_prices(vendor):
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "region_id": ,
    #             "price": ,
    #             "currency": "USD",
    #             "unit": PriceUnit.MONTH,
    #         }
    #     )
    return items
