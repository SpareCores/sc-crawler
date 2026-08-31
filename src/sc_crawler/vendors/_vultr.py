from os import environ

from cachier import cachier
from requests import get

from ..inspector import _extract_manufacturer
from ..lookup import map_compliance_frameworks_to_vendor
from ..sentry import sentry_capture_or_raise
from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    DatabaseEngine,
    DatabaseHaLevel,
    DatabaseHaStrategy,
    DatabaseSecurityFeature,
    DatabaseWireProtocol,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)
from ..utils import _HOURS_PER_MONTH, _MIB_PER_GIB

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

_DATABASE_PLAN_TYPES: dict[str, str] = {
    # Managed DB plan type codes and node-plan tier labels come from:
    # - GET /v2/databases/plans payload (`type`, `id`)
    #   https://www.vultr.com/api/
    # - Node plan naming examples (`vultr-dbaas-[tier]-...`)
    #   https://docs.vultr.com/support/products/managed-databases/how-do-i-identify-the-node-plan-for-my-vultr-managed-database
    # - Provisioning examples that use DB plan ids
    #   https://docs.vultr.com/products/storage/databases/postgresql/provisioning
    "vdb": "Cloud Compute",
    "vc2": "Cloud Compute",
    "cc_hp_amd": "High Performance AMD",
    "cc_hp_intel": "High Performance Intel",
    "occ_gp": "Optimized Cloud Compute General Purpose",
    "occ_so": "Optimized Cloud Compute Storage Optimized",
}

_DATABASE_TIERS = frozenset({"hobbyist", "startup", "business", "premium"})
_DATABASE_PITR_DAYS_BY_TIER: dict[str, int | None] = {
    "hobbyist": None,
    "startup": 2,
    "business": 14,
    "premium": 30,
}

_CPU_MODEL_PREFIXES: tuple[str, ...] = (
    "EPYC ",
    "Grace ",
    "Platinum ",
    "Gold ",
    "E3-",
    "E-",
)

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

# Vultr gpu_type → per-GPU VRAM (GiB) and architecture family.
# https://www.nvidia.com/en-us/data-center/ / https://www.amd.com/en/products/accelerators/instinct/
_GPU_TYPES: dict[str, dict[str, int | str]] = {
    "NVIDIA_A16": {"vram_gb": 16, "family": "Ampere"},
    "NVIDIA_A40": {"vram_gb": 48, "family": "Ampere"},
    "NVIDIA_L40S": {"vram_gb": 48, "family": "Ada Lovelace"},
    "NVIDIA_A100": {"vram_gb": 40, "family": "Ampere"},
    "NVIDIA_A100_PCIE": {"vram_gb": 80, "family": "Ampere"},
    "NVIDIA_A100_SXM": {"vram_gb": 80, "family": "Ampere"},
    "NVIDIA_H100": {"vram_gb": 80, "family": "Hopper"},
    "NVIDIA_B200": {"vram_gb": 192, "family": "Blackwell"},
    "NVIDIA_GH200": {"vram_gb": 96, "family": "Grace Hopper"},
    "AMD_MI300X": {"vram_gb": 192, "family": "CDNA3"},
    "AMD_MI325X": {"vram_gb": 256, "family": "CDNA3"},
    "AMD_MI355X": {"vram_gb": 288, "family": "CDNA4"},
}

# Dedicated Metal GPU (vdm) plans omit gpu_type / gpu_vram_gb / gpu_count in GET /v2/plans.
# https://www.vultr.com/pricing/ https://www.vultr.com/products/bare-metal/
_DEDICATED_METAL_GPU_PLANS: dict[str, dict[str, int | str]] = {
    "vcg-a16-96c-878g-256vram": {
        "gpu_type": "NVIDIA_A16",
        "gpu_count": 16,
        "gpu_vram_total_gb": 256,
    },
    "vcg-a100-96c-896g-320vram": {
        "gpu_type": "NVIDIA_A100",
        "gpu_count": 4,
        "gpu_vram_total_gb": 320,
    },
    "vcg-h100-216c-1914gb-640vram": {
        "gpu_type": "NVIDIA_H100",
        "gpu_count": 8,
        "gpu_vram_total_gb": 640,
    },
    "vcg-b200-248c-2826g-1536vram": {
        "gpu_type": "NVIDIA_B200",
        "gpu_count": 8,
        "gpu_vram_total_gb": 1536,
    },
    "vcg-mi325x-252c-2872g-1536vram": {
        "gpu_type": "AMD_MI325X",
        "gpu_count": 6,
        "gpu_vram_total_gb": 1536,
    },
    "vcg-mi355x-252c-2872g-2304vram": {
        "gpu_type": "AMD_MI355X",
        "gpu_count": 8,
        "gpu_vram_total_gb": 2304,
    },
}

# Vultr Block Storage (VBS) catalog — keys match GET /v2/regions ``options``.
# Performance: https://docs.vultr.com/support/products/storage/what-are-the-performance-expectations-for-block-storage
# VKE CSI: https://docs.vultr.com/how-to-provision-persistent-volume-claims-on-vultr-kubernetes-engine
_BLOCK_STORAGE: dict[str, dict] = {
    "block_storage_high_perf": {
        "name": "NVMe Block Storage",
        "description": "VBS high_perf (CSI vultr-block-storage).",
        "storage_type": StorageType.NVME_SSD,
        "min_size": 10,
        "max_size": 10_000,
        "max_iops": 10_000,
        "max_throughput": 400,
        "price_gb_month": 0.10,
    },
    "block_storage_storage_opt": {
        "name": "HDD Block Storage",
        "description": "VBS storage_opt (CSI vultr-block-storage-hdd).",
        "storage_type": StorageType.HDD,
        "min_size": 40,
        "max_size": 40_000,
        "max_iops": 500,
        "max_throughput": 100,
        "price_gb_month": 0.025,
    },
}


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


def _database_plan_tier(database_id: str) -> str:
    """Return the node-plan tier token from a vultr-dbaas id, or '' if absent."""
    parts = database_id.split("-")
    if len(parts) <= 2:
        return ""
    tier = parts[2].lower()
    return tier if tier in _DATABASE_TIERS else ""


def _database_family_name(plan: dict) -> str:
    """Build readable managed database family from plan id and type."""
    tier = _database_plan_tier(plan.get("id", ""))
    tier_label = tier.title() if tier else ""
    plan_type = plan.get("type") or "Unknown"
    plan_type = _DATABASE_PLAN_TYPES.get(plan_type, plan_type)
    return f"{tier_label} {plan_type}".strip()


def _database_pitr_days(database_id: str) -> int | None:
    """Map Vultr PostgreSQL node-plan tier to PITR retention days."""
    tier = _database_plan_tier(database_id)
    if not tier:
        return None
    return _DATABASE_PITR_DAYS_BY_TIER.get(tier)


def _server_description(
    family: str | None,
    vcpus: int | None,
    memory_amount_mib: int | None,
    storage_size: int | None,
    storage_type: StorageType | None,
    gpu_count: int | float | None = None,
    gpu_model: str | None = None,
    gpu_vram_gb: int | None = None,
) -> str:
    nvme_size = storage_size if storage_type == StorageType.NVME_SSD else 0
    ssd_size = storage_size if storage_type == StorageType.SSD else 0
    memory_size_gb = memory_amount_mib / _MIB_PER_GIB if memory_amount_mib else None
    description_parts = [
        f"{vcpus} vCPUs" if vcpus else None,
        f"{memory_size_gb} GiB RAM" if memory_size_gb else None,
        f"{nvme_size} GB NVMe" if nvme_size else None,
        f"{ssd_size} GB SSD" if ssd_size else None,
        (
            f"{gpu_count}x{gpu_model} {gpu_vram_gb} GiB VRAM"
            if gpu_count and gpu_model and gpu_vram_gb
            else None
        ),
    ]
    description_parts_str = ", ".join(filter(None, description_parts))
    return f"{family} ({description_parts_str})" if family else description_parts_str


def _database_description(
    family: str | None,
    vcpus: int | None,
    memory_amount_mib: int | None,
    storage_size: int | None,
) -> str:
    """Build managed database plan description in server-style format."""
    memory_size_gb = memory_amount_mib / _MIB_PER_GIB if memory_amount_mib else None
    description_parts = [
        f"{vcpus} vCPUs" if vcpus else None,
        f"{memory_size_gb} GiB RAM" if memory_size_gb else None,
        f"{storage_size} GB SSD" if storage_size else None,
    ]
    description_parts_str = ", ".join(filter(None, description_parts))
    return f"{family} ({description_parts_str})" if family else description_parts_str


@cachier(separate_files=True)
def _get_regions():
    response = get(
        "https://api.vultr.com/v2/regions", params={"per_page": 500}, timeout=10
    )
    return response.json()["regions"]


@cachier(separate_files=True)
def _get_plans():
    response = get(
        "https://api.vultr.com/v2/plans", params={"per_page": 500}, timeout=10
    )
    return response.json()["plans"]


@cachier(separate_files=True)
def _get_plans_metal():
    response = get(
        "https://api.vultr.com/v2/plans-metal", params={"per_page": 500}, timeout=10
    )
    return response.json()["plans_metal"]


def _vultr_auth_headers() -> dict[str, str]:
    try:
        api_key = environ["VULTR_API_KEY"]
    except KeyError:
        raise KeyError("Missing environment variable: VULTR_API_KEY") from None
    return {"Authorization": f"Bearer {api_key}"}


@cachier(separate_files=True)
def _get_database_plans():
    response = get(
        "https://api.vultr.com/v2/databases/plans",
        headers=_vultr_auth_headers(),
        params={"engine": "pg", "per_page": 500},
        timeout=10,
    )
    response.raise_for_status()
    return response.json().get("plans", [])


@cachier(separate_files=True)
def _get_database_available_services():
    response = get(
        "https://api.vultr.com/v2/databases/available-services",
        headers=_vultr_auth_headers(),
        params={"per_page": 500},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


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
    for region in regions:
        with sentry_capture_or_raise(vendor=vendor):
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

    There is no concept of having multiple availability zones within
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
    """List all servers from Vultr API.

    Lifecycle: free plan or empty `locations` -> INACTIVE, otherwise ACTIVE.
    """
    plans = _get_plans()
    plans_metal = _get_plans_metal()

    items = []
    for server in plans + plans_metal:
        # CPU
        cpu_model_raw = server.get("cpu_model", "")
        cpu_manufacturer = server.get("cpu_vendor") or server.get("cpu_manufacturer")
        cpu_family = _extract_cpu_family(cpu_model_raw)
        cpu_model = _standardize_cpu_model(cpu_model_raw)
        vcpus = server.get("vcpu_count") or server.get("cpu_threads")
        cpu_cores = server.get("cpu_count")
        # Plan type → CPU allocation (API has no dedicated/shared flag).
        # Shared: vc2, vhp, vhf — https://www.vultr.com/pricing/ ("Cloud Compute" /
        #   "These virtual machines run atop shared vCPUs")
        # Dedicated: voc — same page ("Optimized Cloud Compute" / "fully dedicated")
        # Dedicated: vx1 — https://docs.vultr.com/vultr-vx1-cloud-compute
        # Dedicated: vcg, vdm, and bare metal (type SSD/NVMe from /v2/plans/metal)
        cpu_allocation = (
            CpuAllocation.SHARED
            if server.get("type") in ("vc2", "vhp", "vhf")
            else CpuAllocation.DEDICATED
        )
        cpu_architecture = (
            CpuArchitecture.ARM64 if cpu_family == "Grace" else CpuArchitecture.X86_64
        )
        cpu_speed_mhz = server.get("cpu_mhz")
        cpu_speed_ghz = cpu_speed_mhz / 1000 if cpu_speed_mhz else None

        # Memory
        memory_amount = server["ram"]

        # GPU
        gpu_brand = server.get("gpu_brand", "")
        gpu_type = server.get("gpu_type")
        gpu_vram_total_gb = server.get("gpu_vram_gb") or 0
        gpu_count_from_api = server.get("gpu_count")
        gpu_fallback = _DEDICATED_METAL_GPU_PLANS.get(server["id"])
        if gpu_fallback:
            gpu_type = gpu_type or gpu_fallback.get("gpu_type")
            gpu_vram_total_gb = gpu_vram_total_gb or gpu_fallback.get(
                "gpu_vram_total_gb", 0
            )
            gpu_count_from_api = gpu_count_from_api or gpu_fallback.get("gpu_count")
            if not gpu_brand and gpu_type:
                gpu_brand = gpu_type.split("_")[0]
        gpu_manufacturer_from_type = gpu_type.split("_")[0] if gpu_type else ""
        gpu_manufacturer = _extract_manufacturer(gpu_brand) or _extract_manufacturer(
            gpu_manufacturer_from_type
        )
        gpu_profile = _GPU_TYPES.get(gpu_type, {})
        gpu_vram_gb = gpu_profile.get("vram_gb")
        gpu_family = gpu_profile.get("family")
        gpu_memory_min = (
            int(min(gpu_vram_gb, gpu_vram_total_gb) * _MIB_PER_GIB)
            if gpu_vram_gb and gpu_vram_total_gb
            else 0
        )
        gpu_count = None
        if gpu_count_from_api:
            if isinstance(gpu_count_from_api, str) and "/" in gpu_count_from_api:
                num, den = gpu_count_from_api.split("/", 1)
                gpu_count = round(int(num) / int(den), 4)
            else:
                gpu_count = gpu_count_from_api
        if gpu_count is None:
            gpu_count = (
                round(gpu_vram_total_gb / gpu_vram_gb, 4)
                if gpu_vram_gb and gpu_vram_total_gb
                else 0
            )
        if gpu_type:
            gpu_model_parts = gpu_type.split("_")
            if len(gpu_model_parts) > 1:
                gpu_model = gpu_model_parts[1]
            else:
                gpu_model = gpu_type
        else:
            gpu_model = None

        # Storage
        storage_size_per_disk = server.get("disk")
        storage_type = _storage_type_from_plan(server)
        storage_size = storage_size_per_disk * server.get("disk_count", 1)
        family = _PLAN_TYPES.get(server["type"])

        description = _server_description(
            family,
            vcpus,
            memory_amount,
            storage_size,
            storage_type,
            gpu_count,
            gpu_model,
            gpu_vram_gb,
        )

        item = {
            "vendor_id": vendor.vendor_id,
            "server_id": server["id"],
            "name": server["id"],
            "api_reference": server["id"],
            "display_name": server["id"],
            "description": description,
            "family": family,
            "vcpus": vcpus,
            "hypervisor": None,
            "cpu_allocation": cpu_allocation,
            "cpu_cores": cpu_cores,
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
            "memory_amount": memory_amount,
            "memory_generation": None,
            "memory_speed": None,
            "memory_ecc": None,
            "gpu_count": gpu_count,
            "gpu_memory_min": gpu_memory_min,
            "gpu_memory_total": (
                int(gpu_vram_total_gb * _MIB_PER_GIB) if gpu_vram_total_gb else 0
            ),
            "gpu_manufacturer": gpu_manufacturer,
            "gpu_family": gpu_family,
            "gpu_model": gpu_model,
            "gpus": [],
            "storage_size": storage_size,
            "storage_type": storage_type,
            "storages": [],
            "network_speed_baseline": None,
            # link_speed is Gbps when present ("up to" / provisioned; no documented baseline)
            # link_type (shared|dedicated) is network uplink, not mapped to a column
            "network_speed_max": server.get("link_speed"),
            "network_storage_speed_baseline": None,
            "network_storage_speed_max": None,
            "inbound_traffic": 0,
            "outbound_traffic": server.get("bandwidth", 0),
            # the smallest plan is IPv6-only
            "ipv4": 0 if server["id"] == "vc2-1c-0.5gb-v6" else 1,
        }

        # exclude limited plans not generally available without scale
        if item["server_id"] == "vc2-1c-0.5gb-free" or not server.get("locations"):
            item["status"] = Status.INACTIVE
        else:
            item["status"] = Status.ACTIVE

        items.append(item)
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
    for storage_id, spec in _BLOCK_STORAGE.items():
        items.append(
            {
                "storage_id": storage_id,
                "vendor_id": vendor.vendor_id,
                "name": spec["name"],
                "description": spec["description"],
                "storage_type": spec["storage_type"],
                "max_iops": spec["max_iops"],
                "max_throughput": spec["max_throughput"],
                "min_size": spec["min_size"],
                "max_size": spec["max_size"],
            }
        )
    return items


def inventory_storage_prices(vendor):
    items = []
    regions = _get_regions()
    for region in regions:
        options = region.get("options", [])
        for storage_id in _BLOCK_STORAGE.keys():
            if storage_id not in options:
                continue
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region["id"],
                    "storage_id": storage_id,
                    "unit": PriceUnit.GB_MONTH,
                    "price": _BLOCK_STORAGE[storage_id]["price_gb_month"],
                    "currency": "USD",
                }
            )
    return items


def inventory_traffic_prices(vendor):
    """Public network traffic rates (flat worldwide).

    Ingress is free. Outbound overage beyond pooled plan + account quota is
    billed per GB; included allowances are on each server plan ``bandwidth`` field.

    Source: <https://docs.vultr.com/support/platform/billing/what-is-the-bandwidth-overage-rate>
    """
    items = []
    regions = _get_regions()
    for region in regions:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region["id"],
                "price": 0,
                "price_tiered": [],
                "currency": "USD",
                "unit": PriceUnit.GB_MONTH,
                "direction": TrafficDirection.IN,
            }
        )
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region["id"],
                "price": 0.01,
                "price_tiered": [],
                "currency": "USD",
                "unit": PriceUnit.GB_MONTH,
                "direction": TrafficDirection.OUT,
            }
        )
    return items


def inventory_ipv4_prices(vendor):
    """Reserved / additional public IPv4 (flat worldwide).

    Primary instance IPv4 is included in compute pricing; this is the published
    rate for reserved IPs (also used for extra addresses).

    Source: <https://docs.vultr.com/support/products/network/are-reserved-ips-free>
    """
    items = []
    regions = _get_regions()
    for region in regions:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region["id"],
                "price": 3.0,
                "currency": "USD",
                "unit": PriceUnit.MONTH,
            }
        )
    return items


def inventory_databases(vendor):
    """List Vultr managed PostgreSQL plans.

    - Provisioning uses POST /v2/databases with `plan` and `database_engine`.
    - Plan ids come from GET /v2/databases/plans.
    - Vultr Managed Databases are managed clusters, not plain VM images.
    https://docs.vultr.com/products/storage/databases/postgresql/provisioning
    https://docs.vultr.com/products/storage/databases
    """
    plans = _get_database_plans()
    services = _get_database_available_services()
    # Source: GET /v2/databases/available-services (`available_services.pg`).
    # https://www.vultr.com/api/
    versions = services.get("available_services", {}).get("pg", [])
    items = []
    for plan in plans:
        database_id = plan.get("id")
        vcpus = plan.get("vcpu_count")
        memory = plan.get("ram")
        storage_size = plan.get("disk")
        node_count = plan.get("number_of_nodes")
        # Replica nodes are read-only failover replicas. We model this as
        # readable-cluster HA when a plan includes more than one node.
        # https://docs.vultr.com/support/products/managed-databases/what-are-replica-nodes
        # https://docs.vultr.com/support/products/managed-databases/what-type-of-replica-nodes-are-attached-to-a-vultr-managed-database
        # https://docs.vultr.com/support/products/managed-databases/how-does-vultr-managed-databases-handle-automated-failover-in-multi-node-clusters
        if node_count > 1:
            ha = [DatabaseHaLevel.SINGLE_ZONE]
            ha_strategy = [DatabaseHaStrategy.READABLE_CLUSTER]
        else:
            ha = [DatabaseHaLevel.NONE]
            ha_strategy = [DatabaseHaStrategy.NONE]
        # Plans with zero locations are not currently orderable in any region.
        status = Status.ACTIVE if plan.get("locations") else Status.INACTIVE
        family = _database_family_name(plan)
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "database_id": database_id,
                "name": database_id,
                "display_name": plan.get("name", database_id),
                "description": _database_description(
                    f"Vultr PostgreSQL {family}", vcpus, memory, storage_size
                ),
                "api_reference": database_id,
                # API/IaC provisioning references this plan id and engine.
                # https://docs.vultr.com/products/storage/databases/postgresql/provisioning
                "api_reference_object": {
                    "plan": database_id,
                    "database_engine": "pg",
                },
                # Managed Databases are provisioned as managed clusters, not as
                # plain VM images with a stable 1:1 server SKU mapping.
                # https://docs.vultr.com/products/storage/databases
                "server_id": None,
                "engine": DatabaseEngine.POSTGRESQL,
                "wire_protocol": DatabaseWireProtocol.POSTGRESQL,
                "engine_versions": versions,
                "family": family,
                "vcpus": vcpus,
                "memory_amount": memory,
                "storage_size": storage_size,
                # Vultr does not expose explicit storage extra min/max/autosize - only bundled storage size is present
                "storage_extra_min": 0,
                "storage_extra_max": 0,
                "storage_extra_autosize": False,
                "ha": ha,
                "ha_strategy": ha_strategy,
                "max_read_replicas": max(node_count - 1, 0),
                # PostgreSQL settings are configurable via Advanced Configuration.
                # https://docs.vultr.com/products/storage/databases/postgresql/management/settings/configuration-options
                "custom_config": True,
                # Vultr supports enabling PostgreSQL extensions.
                # https://docs.vultr.com/support/products/managed-databases/how-do-i-enable-extensions-in-a-vultr-managed-postgresql-database
                "custom_extensions": True,
                # Vultr documents encryption at rest for Managed Databases.
                # https://docs.vultr.com/support/products/managed-databases/how-does-vultr-protect-my-database-data-at-rest
                "disk_encryption": True,
                # Vultr supports scheduling upgrade windows for managed
                # PostgreSQL version upgrades.
                # https://docs.vultr.com/products/storage/databases/postgresql/management/upgrade-databases
                "auto_upgrade_versions": True,
                # PostgreSQL plans are automatically backed up.
                # https://docs.vultr.com/support/products/managed-databases/is-my-vultr-managed-mysql-or-postgresql-database-backed-up
                "scheduled_backups": True,
                # PostgreSQL FAQ documents PITR retention by node-plan tier:
                # Premium=30 days, Business=14 days, Startup=2 days, Hobbyist=None.
                # https://docs.vultr.com/products/managed-database/postgresql/faq
                "continuous_backups": _database_pitr_days(database_id),
                # Vultr Managed PostgreSQL includes PgBouncer and supports
                # managing connection pools.
                # https://docs.vultr.com/products/storage/databases/postgresql/management/pgbouncer
                # https://docs.vultr.com/products/storage/databases/postgresql/management/connection/connection-pools
                "connection_pool": True,
                # Usage graphs and API/CLI usage endpoints cover CPU, memory,
                # disk and network monitoring for managed databases.
                # https://docs.vultr.com/products/storage/databases/mysql/management/monitor-databases
                "system_monitoring": True,
                "database_monitoring": True,
                # Vultr exposes manual advanced-option tuning, but no documented
                # built-in auto-tuning advisor or auto-apply feature.
                # https://docs.vultr.com/reference/vultr-cli/database/advanced-option/update
                # https://docs.vultr.com/products/storage/databases/postgresql/management/settings/configuration-options
                "autotuning_advice": None,
                "autotuning_apply": None,
                # Managed Databases are advertised with a 99.99% SLA.
                # https://www.vultr.com/products/managed-databases/
                "sla": 99.99,
                "status": status,
                # Provisioning supports `trusted_ips` and `vpc_id`.
                # https://docs.vultr.com/products/storage/databases/postgresql/provisioning
                # Vultr documents TLS in transit for Managed Databases.
                # https://docs.vultr.com/support/products/managed-databases/is-a-vultr-managed-database-secure
                "security_features": [
                    DatabaseSecurityFeature.IP_FILTERING,
                    DatabaseSecurityFeature.PRIVATE_NETWORK,
                    DatabaseSecurityFeature.ENFORCED_TLS,
                ],
            }
        )
    return items


def inventory_database_prices(vendor):
    databases = {database.database_id: database for database in vendor.databases}
    plans = _get_database_plans()
    items = []
    for plan in plans:
        database_id = plan.get("id")
        if database_id not in databases:
            continue
        if not plan.get("locations"):
            continue
        node_count = plan.get("number_of_nodes")
        if node_count > 1:
            ha = DatabaseHaLevel.SINGLE_ZONE
            ha_strategy = DatabaseHaStrategy.READABLE_CLUSTER
        else:
            ha = DatabaseHaLevel.NONE
            ha_strategy = DatabaseHaStrategy.NONE
        hourly_cost = plan.get("hourly_cost")
        monthly_cost = plan.get("monthly_cost")
        if hourly_cost is not None:
            hourly_price = hourly_cost
        elif monthly_cost is not None:
            hourly_price = monthly_cost / _HOURS_PER_MONTH
        else:
            continue
        price_tiered = []
        if monthly_cost is not None and hourly_price:
            monthly_cap = int(monthly_cost / hourly_price)
            price_tiered = [
                {"lower": 0, "upper": monthly_cap, "price": hourly_price},
                {"lower": monthly_cap + 1, "upper": "Infinity", "price": 0},
            ]
        for location in plan.get("locations", []):
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": location,
                    "database_id": database_id,
                    "allocation": Allocation.ONDEMAND,
                    "ha": ha,
                    "ha_strategy": ha_strategy,
                    "unit": PriceUnit.HOUR,
                    "price": hourly_price,
                    "price_upfront": 0,
                    "price_tiered": price_tiered,
                    "currency": plan.get("currency", "USD"),
                }
            )
    return items


def inventory_database_storages(vendor):
    """Vultr managed PostgreSQL storage is bundled into DB plans.

    Resizing storage is done by changing the database node plan; there is no
    separate DB storage catalog product exposed by the public API.
    https://docs.vultr.com/products/storage/databases/postgresql/management/resize-databases
    """
    return []


def inventory_database_storage_prices(vendor):
    """No standalone Vultr managed DB storage price meters are exposed."""
    return []
