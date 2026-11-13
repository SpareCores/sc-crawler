"""Inventory of Oracle Cloud Infrastructure via its API and the public price list: servers, storages, traffic and IPv4 addresses, with their prices."""

from functools import cache
from math import ceil
from os import environ, getenv
from re import compile as recompile
from re import search, sub
from typing import Any

import oci
from cachier import cachier
from requests import get

from ..inspector import _extract_manufacturer
from ..logger import logger
from ..lookup import map_compliance_frameworks_to_vendor
from ..sentry import sentry_capture_or_raise
from ..table_fields import (
    AcceleratorType,
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    Disk,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)
from ..utils import _MIB_PER_GIB
from ..vendor_helpers import parallel_fetch_servers

_API_TIMEOUT = 30
# https://docs.oracle.com/en-us/iaas/Content/GSG/Tasks/signingup_topic-Estimating_Costs.htm
_PRICE_LIST_URL = "https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/"

# Curated location of the commercial (OC1 realm) regions, as the API only returns
# the region identifier and key. Names, cities and countries are from
# <https://docs.oracle.com/en-us/iaas/Content/General/Concepts/regions.htm>,
# coordinates are city-level.
_REGION_LOCATIONS: dict[str, dict] = {
    "af-casablanca-1": {
        "name": "Morocco West (Casablanca)",
        "country_id": "MA",
        "city": "Casablanca",
        "lat": 33.5731,
        "lon": -7.5898,
    },
    "af-johannesburg-1": {
        "name": "South Africa Central (Johannesburg)",
        "country_id": "ZA",
        "city": "Johannesburg",
        "lat": -26.2041,
        "lon": 28.0473,
    },
    "ap-batam-1": {
        "name": "Indonesia North (Batam)",
        "country_id": "ID",
        "city": "Batam",
        "lat": 1.0456,
        "lon": 104.0305,
    },
    "ap-chuncheon-1": {
        "name": "South Korea North (Chuncheon)",
        "country_id": "KR",
        "city": "Chuncheon",
        "lat": 37.8813,
        "lon": 127.7298,
    },
    "ap-hyderabad-1": {
        "name": "India South (Hyderabad)",
        "country_id": "IN",
        "state": "Telangana",
        "city": "Hyderabad",
        "lat": 17.3850,
        "lon": 78.4867,
    },
    "ap-kulai-2": {
        "name": "Malaysia West 2 (Kulai)",
        "country_id": "MY",
        "state": "Johor",
        "city": "Kulai",
        "lat": 1.6561,
        "lon": 103.6032,
    },
    "ap-melbourne-1": {
        "name": "Australia Southeast (Melbourne)",
        "country_id": "AU",
        "state": "Victoria",
        "city": "Melbourne",
        "lat": -37.8136,
        "lon": 144.9631,
    },
    "ap-mumbai-1": {
        "name": "India West (Mumbai)",
        "country_id": "IN",
        "state": "Maharashtra",
        "city": "Mumbai",
        "lat": 19.0760,
        "lon": 72.8777,
    },
    "ap-osaka-1": {
        "name": "Japan Central (Osaka)",
        "country_id": "JP",
        "city": "Osaka",
        "lat": 34.6937,
        "lon": 135.5023,
    },
    "ap-seoul-1": {
        "name": "South Korea Central (Seoul)",
        "country_id": "KR",
        "city": "Seoul",
        "lat": 37.5665,
        "lon": 126.9780,
    },
    "ap-singapore-1": {
        "name": "Singapore (Singapore)",
        "country_id": "SG",
        "city": "Singapore",
        "lat": 1.3521,
        "lon": 103.8198,
    },
    "ap-singapore-2": {
        "name": "Singapore West (Singapore)",
        "country_id": "SG",
        "city": "Singapore",
        "lat": 1.3521,
        "lon": 103.8198,
    },
    "ap-sydney-1": {
        "name": "Australia East (Sydney)",
        "country_id": "AU",
        "state": "New South Wales",
        "city": "Sydney",
        "lat": -33.8688,
        "lon": 151.2093,
    },
    "ap-tokyo-1": {
        "name": "Japan East (Tokyo)",
        "country_id": "JP",
        "city": "Tokyo",
        "lat": 35.6762,
        "lon": 139.6503,
    },
    "ca-montreal-1": {
        "name": "Canada Southeast (Montreal)",
        "country_id": "CA",
        "state": "Quebec",
        "city": "Montreal",
        "lat": 45.5019,
        "lon": -73.5674,
    },
    "ca-toronto-1": {
        "name": "Canada Southeast (Toronto)",
        "country_id": "CA",
        "state": "Ontario",
        "city": "Toronto",
        "lat": 43.6532,
        "lon": -79.3832,
    },
    "eu-amsterdam-1": {
        "name": "Netherlands Northwest (Amsterdam)",
        "country_id": "NL",
        "city": "Amsterdam",
        "lat": 52.3676,
        "lon": 4.9041,
    },
    "eu-frankfurt-1": {
        "name": "Germany Central (Frankfurt)",
        "country_id": "DE",
        "state": "Hesse",
        "city": "Frankfurt",
        "lat": 50.1109,
        "lon": 8.6821,
    },
    "eu-madrid-1": {
        "name": "Spain Central (Madrid)",
        "country_id": "ES",
        "city": "Madrid",
        "lat": 40.4168,
        "lon": -3.7038,
    },
    "eu-madrid-3": {
        "name": "Spain Central (Madrid 3)",
        "country_id": "ES",
        "city": "Madrid",
        "lat": 40.4168,
        "lon": -3.7038,
    },
    "eu-marseille-1": {
        "name": "France South (Marseille)",
        "country_id": "FR",
        "city": "Marseille",
        "lat": 43.2965,
        "lon": 5.3698,
    },
    "eu-milan-1": {
        "name": "Italy Northwest (Milan)",
        "country_id": "IT",
        "city": "Milan",
        "lat": 45.4642,
        "lon": 9.1900,
    },
    "eu-paris-1": {
        "name": "France Central (Paris)",
        "country_id": "FR",
        "city": "Paris",
        "lat": 48.8566,
        "lon": 2.3522,
    },
    "eu-stockholm-1": {
        "name": "Sweden Central (Stockholm)",
        "country_id": "SE",
        "city": "Stockholm",
        "lat": 59.3293,
        "lon": 18.0686,
    },
    "eu-turin-1": {
        "name": "Italy North (Turin)",
        "country_id": "IT",
        "city": "Turin",
        "lat": 45.0703,
        "lon": 7.6869,
    },
    "eu-zurich-1": {
        "name": "Switzerland North (Zurich)",
        "country_id": "CH",
        "city": "Zurich",
        "lat": 47.3769,
        "lon": 8.5417,
    },
    "il-jerusalem-1": {
        "name": "Israel Central (Jerusalem)",
        "country_id": "IL",
        "city": "Jerusalem",
        "lat": 31.7683,
        "lon": 35.2137,
    },
    "me-abudhabi-1": {
        "name": "UAE Central (Abu Dhabi)",
        "country_id": "AE",
        "city": "Abu Dhabi",
        "lat": 24.4539,
        "lon": 54.3773,
    },
    "me-dubai-1": {
        "name": "UAE East (Dubai)",
        "country_id": "AE",
        "city": "Dubai",
        "lat": 25.2048,
        "lon": 55.2708,
    },
    "me-jeddah-1": {
        "name": "Saudi Arabia West (Jeddah)",
        "country_id": "SA",
        "city": "Jeddah",
        "lat": 21.4858,
        "lon": 39.1925,
    },
    "me-riyadh-1": {
        "name": "Saudi Arabia Central (Riyadh)",
        "country_id": "SA",
        "city": "Riyadh",
        "lat": 24.7136,
        "lon": 46.6753,
    },
    "mx-monterrey-1": {
        "name": "Mexico Northeast (Monterrey)",
        "country_id": "MX",
        "state": "Nuevo León",
        "city": "Monterrey",
        "lat": 25.6866,
        "lon": -100.3161,
    },
    "mx-queretaro-1": {
        "name": "Mexico Central (Queretaro)",
        "country_id": "MX",
        "state": "Querétaro",
        "city": "Queretaro",
        "lat": 20.5888,
        "lon": -100.3899,
    },
    "sa-bogota-1": {
        "name": "Colombia Central (Bogota)",
        "country_id": "CO",
        "city": "Bogota",
        "lat": 4.7110,
        "lon": -74.0721,
    },
    "sa-santiago-1": {
        "name": "Chile Central (Santiago)",
        "country_id": "CL",
        "city": "Santiago",
        "lat": -33.4489,
        "lon": -70.6693,
    },
    "sa-saopaulo-1": {
        "name": "Brazil East (Sao Paulo)",
        "country_id": "BR",
        "state": "São Paulo",
        "city": "Sao Paulo",
        "lat": -23.5505,
        "lon": -46.6333,
    },
    "sa-valparaiso-1": {
        "name": "Chile West (Valparaiso)",
        "country_id": "CL",
        "city": "Valparaiso",
        "lat": -33.0472,
        "lon": -71.6127,
    },
    "sa-vinhedo-1": {
        "name": "Brazil Southeast (Vinhedo)",
        "country_id": "BR",
        "state": "São Paulo",
        "city": "Vinhedo",
        "lat": -23.0297,
        "lon": -46.9753,
    },
    "uk-cardiff-1": {
        "name": "UK West (Newport)",
        "country_id": "GB",
        "state": "Wales",
        "city": "Newport",
        "lat": 51.5842,
        "lon": -2.9977,
    },
    "uk-london-1": {
        "name": "UK South (London)",
        "country_id": "GB",
        "state": "England",
        "city": "London",
        "lat": 51.5074,
        "lon": -0.1278,
    },
    "us-ashburn-1": {
        "name": "US East (Ashburn)",
        "country_id": "US",
        "state": "Virginia",
        "city": "Ashburn",
        "lat": 39.0438,
        "lon": -77.4874,
    },
    "us-chicago-1": {
        "name": "US Midwest (Chicago)",
        "country_id": "US",
        "state": "Illinois",
        "city": "Chicago",
        "lat": 41.8781,
        "lon": -87.6298,
    },
    "us-phoenix-1": {
        "name": "US West (Phoenix)",
        "country_id": "US",
        "state": "Arizona",
        "city": "Phoenix",
        "lat": 33.4484,
        "lon": -112.0740,
    },
    "us-sanjose-1": {
        "name": "US West (San Jose)",
        "country_id": "US",
        "state": "California",
        "city": "San Jose",
        "lat": 37.3382,
        "lon": -121.8863,
    },
}

# VM or BM (bare metal) prefix, then the series, then the size of the shape,
# e.g. VM.Standard.E5.Flex, VM.Standard.E2.1.Micro or BM.GPU.A100-v2.8
_SHAPE_RE = recompile(r"^(VM|BM)\.(.+?)\.(?:Flex|\d+(?:\.Micro)?)$")

# https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm
_SHAPE_FAMILIES: dict[str, str] = {
    "Standard": "Standard",
    "DenseIO": "Dense I/O",
    "GPU": "GPU",
    "HPC": "HPC",
    "Optimized": "Optimized",
}

# An OCPU is a physical core with two threads (vCPUs) on x86, while the Arm
# shapes have no SMT, and the OCPU is defined per processor generation:
# "1 OCPU on Arm A1 = 1 core on Arm A1 or 1 vCPU" and
# "1 OCPU on Arm A2 and A4 = 2 cores on Arm A2 and A4 or 2 vCPUs" as per
# https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm
_X86_VCPUS_PER_OCPU = 2
_ARM_VCPUS_PER_OCPU: dict[str, int] = {"A1": 1, "A2": 2, "A4": 2}

# Flexible shapes can be launched with any number of OCPUs and memory within
# the limits of the shape, so a grid of the below OCPU counts (and the maximum
# of the shape) and memory per vCPU ratios (GiB) is listed as separate servers.
_FLEX_OCPUS: tuple[int, ...] = (1, 2, 4, 8, 16, 32, 64)
_FLEX_MEMORY_GB_PER_VCPU: tuple[int, ...] = (2, 4, 8)

# Flexible Dense I/O shapes come in fixed configurations: memory is fixed per
# OCPU, and a 6.8 TB NVMe drive is attached per 8 OCPUs, as per
# https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm#vm-dense
_DENSE_IO_FLEX: dict[str, dict] = {
    "VM.DenseIO.E4.Flex": {"ocpus": (8, 16, 32), "memory_gb_per_ocpu": 16},
    "VM.DenseIO.E5.Flex": {
        "ocpus": (8, 16, 24, 32, 40, 48),
        "memory_gb_per_ocpu": 12,
    },
    "VM.DenseIO.E6.Ax.Flex": {
        "ocpus": (8, 16, 24, 32, 40, 48),
        "memory_gb_per_ocpu": 12,
    },
}
_DENSE_IO_FLEX_OCPUS_PER_DISK = 8
_DENSE_IO_FLEX_DISK_GB = 6800

# GPU model and per-GPU memory (GB) of the GPU shape series, from the "GPU
# Shapes" tables (GPU memory of the shape divided by the number of GPUs) at
# https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm#bm-gpu
_GPU_SERIES: dict[str, dict] = {
    "GPU2": {"model": "P100", "vram_gb": 16, "family": "Pascal"},
    "GPU3": {"model": "V100", "vram_gb": 16, "family": "Volta"},
    "GPU4": {"model": "A100", "vram_gb": 40, "family": "Ampere"},
    "GPU.A10": {"model": "A10", "vram_gb": 24, "family": "Ampere"},
    "GPU.A100-v2": {"model": "A100", "vram_gb": 80, "family": "Ampere"},
    "GPU.L40S": {"model": "L40S", "vram_gb": 48, "family": "Ada Lovelace"},
    "GPU.H100": {"model": "H100", "vram_gb": 80, "family": "Hopper"},
    "GPU.H200": {"model": "H200", "vram_gb": 141, "family": "Hopper"},
    "GPU.B200": {"model": "B200", "vram_gb": 180, "family": "Blackwell"},
    "GPU.B300": {"model": "B300", "vram_gb": 262.5, "family": "Blackwell"},
    "GPU.GB200": {"model": "GB200", "vram_gb": 192, "family": "Blackwell"},
    "GPU.GB300": {"model": "GB300", "vram_gb": 278, "family": "Blackwell"},
    "GPU.RTXPRO": {"model": "RTX PRO 6000", "vram_gb": 96, "family": "Blackwell"},
    "GPU.MI300X": {
        "manufacturer": "AMD",
        "model": "MI300X",
        "vram_gb": 192,
        "family": "CDNA3",
    },
    "GPU.MI355X": {
        "manufacturer": "AMD",
        "model": "MI355X",
        "vram_gb": 288,
        "family": "CDNA4",
    },
}

# Block Volume performance levels with the Volume Performance Units (VPU) per GB,
# IOPS and throughput (MB/s) limits per volume, as per
# https://docs.oracle.com/en-us/iaas/Content/Block/Concepts/blockvolumeperformance.htm
# Ultra High Performance volumes can be configured with 30-120 VPUs per GB, and
# are listed with the minimum.
_BLOCK_VOLUMES: dict[str, dict] = {
    "lower-cost": {
        "name": "Block Volume Lower Cost",
        "description": "For throughput intensive workloads with large sequential I/O (2 IOPS/GB, 0 VPU/GB). Not available for boot volumes.",
        "vpus": 0,
        "max_iops": 3_000,
        "max_throughput": 480,
    },
    "balanced": {
        "name": "Block Volume Balanced",
        "description": "Default performance level for boot and block volumes (60 IOPS/GB, 10 VPUs/GB).",
        "vpus": 10,
        "max_iops": 25_000,
        "max_throughput": 480,
    },
    "higher-performance": {
        "name": "Block Volume Higher Performance",
        "description": "For workloads with high I/O requirements (75 IOPS/GB, 20 VPUs/GB).",
        "vpus": 20,
        "max_iops": 50_000,
        "max_throughput": 680,
    },
    "ultra-high-performance": {
        "name": "Block Volume Ultra High Performance",
        "description": "For workloads with the highest I/O requirements (90 IOPS/GB at 30 VPUs/GB, configurable up to 225 IOPS/GB, 300,000 IOPS and 2,680 MB/s per volume at 120 VPUs/GB).",
        "vpus": 30,
        "max_iops": 75_000,
        "max_throughput": 880,
    },
}
# https://www.oracle.com/cloud/storage/block-volumes/faq/
_BLOCK_VOLUME_MIN_SIZE = 50
_BLOCK_VOLUME_MAX_SIZE = 32 * 1024

# Part numbers of the public price list by shape series, optionally prefixed by
# VM or BM when the part differs. The price list has no reference to the shapes,
# so this is a manual mapping based on the display name of the parts (the hardware
# generation of the series, e.g. X9 for Standard3 and Optimized3) and
# https://www.oracle.com/cloud/compute/pricing/
# The price of a server is the sum of its OCPUs, memory (GB) and local NVMe
# storage (TB) multiplied by the hourly price of the related parts. Parts
# without a memory price include the memory, and the hourly price per GPU
# includes the OCPUs, memory and local storage of the shape.
_SHAPE_PRICE_PARTS: dict[str, dict[str, str]] = {
    # Compute - Virtual Machine Standard - X5 / Bare Metal Standard - X5
    "VM.Standard1": {"ocpu": "B88317"},
    "BM.Standard1": {"ocpu": "B88315"},
    # Compute - Virtual Machine Standard - B1 / Bare Metal Standard - B1
    "VM.Standard.B1": {"ocpu": "B91120"},
    "BM.Standard.B1": {"ocpu": "B91119"},
    # Compute - Virtual Machine Standard - X7 / Bare Metal Standard - X7
    "VM.Standard2": {"ocpu": "B88514"},
    "BM.Standard2": {"ocpu": "B88513"},
    # Compute - Standard - X9
    "Standard3": {"ocpu": "B94176", "memory": "B94177"},
    # OCI - Compute - Standard - X12 Ax
    "Standard4.Ax": {"ocpu": "B112141", "memory": "B112142"},
    # Compute - Standard - E2
    "Standard.E2": {"ocpu": "B90425"},
    "Standard.E3": {"ocpu": "B92306", "memory": "B92307"},
    "Standard.E4": {"ocpu": "B93113", "memory": "B93114"},
    "Standard.E5": {"ocpu": "B97384", "memory": "B97385"},
    "Standard.E6": {"ocpu": "B111129", "memory": "B111130"},
    "Standard.E6.Ax": {"ocpu": "B112530", "memory": "B112531"},
    "Standard.A1": {"ocpu": "B93297", "memory": "B93298"},
    "Standard.A2": {"ocpu": "B109529", "memory": "B109530"},
    "Standard.A4": {"ocpu": "B112145", "memory": "B112146"},
    "Standard.A4.Ax": {"ocpu": "B112532", "memory": "B112533"},
    # Compute - Optimized - X9
    "Optimized3": {"ocpu": "B93311", "memory": "B93312"},
    # Compute - Virtual Machine Dense I/O - X7 / Bare Metal Dense I/O - X7
    "VM.DenseIO2": {"ocpu": "B88516"},
    "BM.DenseIO2": {"ocpu": "B88515"},
    "DenseIO.E4": {"ocpu": "B93121", "memory": "B93122", "nvme": "B93123"},
    "DenseIO.E5": {"ocpu": "B98202", "memory": "B98203", "nvme": "B98204"},
    "DenseIO.E6.Ax": {"ocpu": "B112556", "memory": "B112557", "nvme": "B112558"},
    # Compute - Bare Metal Standard - HPC - X7
    "BM.HPC2": {"ocpu": "B90398"},
    # Compute - Virtual Machine GPU Standard - X7 / Bare Metal GPU Standard - X7
    "VM.GPU2": {"gpu": "B88518"},
    "BM.GPU2": {"gpu": "B88517"},
    # Compute - GPU Standard - V2
    "GPU3": {"gpu": "B89734"},
    # Compute - GPU - E3
    "GPU4": {"gpu": "B92740"},
    "GPU.A10": {"gpu": "B95909"},
    "GPU.A100-v2": {"gpu": "B95907"},
    "GPU.L40S": {"gpu": "B109479"},
    "GPU.H100": {"gpu": "B98415"},
    "GPU.H200": {"gpu": "B110519"},
    "GPU.B200": {"gpu": "B110978"},
    "GPU.B300": {"gpu": "B112237"},
    "GPU.GB200": {"gpu": "B110979"},
    "GPU.GB300": {"gpu": "B112140"},
    "GPU.RTXPRO": {"gpu": "B112613"},
    "GPU.MI300X": {"gpu": "B109485"},
    "GPU.MI355X": {"gpu": "B111758"},
}

# VM shape series supporting preemptible capacity, which "costs 50% less than
# on-demand capacity in all regions" as per
# https://docs.oracle.com/en-us/iaas/Content/Compute/Concepts/preemptible.htm
# Not available for bare metal, burstable and extended memory instances.
_PREEMPTIBLE_SERIES = frozenset(
    {
        "Standard1",
        "Standard.B1",
        "Standard2",
        "Standard3",
        "Standard.E2",
        "Standard.E3",
        "Standard.E4",
        "Standard.E5",
        "Standard.E6",
        "Standard.A1",
        "Standard.A4",
        "DenseIO1",
        "DenseIO2",
        "GPU2",
        "GPU3",
        "Optimized3",
    }
)
_PREEMPTIBLE_DISCOUNT = 0.5

# Block Volume storage (GB/month) and Volume Performance Unit (per GB/month) parts
_BLOCK_VOLUME_STORAGE_PART = "B91961"
_BLOCK_VOLUME_VPU_PART = "B91962"

# Outbound data transfer parts of the price list by the prefix of the region:
# - B88327: Originating in North America, Europe, and UK
# - B93455: Originating in APAC, Japan, and South America
# - B93456: Originating in Middle East and Africa
# NOTE the Mexican regions are not named in any of the groups, and are listed
# with North America based on their location.
_EGRESS_PARTS: dict[str, str] = {
    "us": "B88327",
    "ca": "B88327",
    "mx": "B88327",
    "eu": "B88327",
    "uk": "B88327",
    "ap": "B93455",
    "sa": "B93455",
    "me": "B93456",
    "il": "B93456",
    "af": "B93456",
}
# tiered prices of the price list have no upper limit in the last tier
_PRICE_RANGE_INFINITY = 999999999999999


@cache
def _config() -> dict:
    """Build the OCI SDK configuration for API key based authentication.

    Environment variables are preferred (all required when `OCI_TENANCY_OCID`
    is set):

    - `OCI_USER_OCID`
    - `OCI_TENANCY_OCID`
    - `OCI_FINGERPRINT`
    - `OCI_REGION`: the home region of the tenancy (e.g. eu-frankfurt-1)
    - `OCI_PRIVATE_KEY` (PEM content) or `OCI_PRIVATE_KEY_PATH`

    Otherwise falling back to the standard `~/.oci/config` file, using the
    profile set in `OCI_CONFIG_PROFILE` (`DEFAULT` if not set).
    """
    if "OCI_TENANCY_OCID" not in environ:
        return oci.config.from_file(
            profile_name=getenv("OCI_CONFIG_PROFILE", oci.config.DEFAULT_PROFILE)
        )
    for ev in ["OCI_USER_OCID", "OCI_FINGERPRINT", "OCI_REGION"]:
        if ev not in environ:
            raise KeyError(f"Missing environment variable: {ev}")
    config = {
        "user": environ["OCI_USER_OCID"],
        "tenancy": environ["OCI_TENANCY_OCID"],
        "fingerprint": environ["OCI_FINGERPRINT"],
        "region": environ["OCI_REGION"],
    }
    if "OCI_PRIVATE_KEY" in environ:
        config["key_content"] = environ["OCI_PRIVATE_KEY"]
    elif "OCI_PRIVATE_KEY_PATH" in environ:
        config["key_file"] = environ["OCI_PRIVATE_KEY_PATH"]
    else:
        raise KeyError(
            "Missing environment variable: OCI_PRIVATE_KEY or OCI_PRIVATE_KEY_PATH"
        )
    oci.config.validate_config(config)
    return config


@cache
def _client(client_class: type, region: str | None = None) -> Any:
    """Create an OCI SDK client in a region, defaulting to the home region."""
    config = _config()
    if region:
        config = config | {"region": region}
    return client_class(config, retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY)


@cachier()
def _get_regions() -> list[dict]:
    """List all regions of the realm (ListRegions).

    Reference: <https://docs.oracle.com/en-us/iaas/api/#/en/identity/20160918/Region/ListRegions>
    """
    # example response (after `oci.util.to_dict`):
    # [
    #     {'key': 'AMS', 'name': 'eu-amsterdam-1'},
    #     {'key': 'ARN', 'name': 'eu-stockholm-1'},
    #     # ...
    # ]
    regions = _client(oci.identity.IdentityClient).list_regions().data
    return oci.util.to_dict(regions)


@cachier()
def _get_region_subscriptions() -> list[dict]:
    """List the regions the tenancy is subscribed to (ListRegionSubscriptions).

    Reference: <https://docs.oracle.com/en-us/iaas/api/#/en/identity/20160918/RegionSubscription/ListRegionSubscriptions>
    """
    # example response (after `oci.util.to_dict`):
    # [
    #     {
    #         'region_key': 'FRA',
    #         'region_name': 'eu-frankfurt-1',
    #         'status': 'READY',
    #         'is_home_region': True,
    #     },
    #     # ...
    # ]
    subscriptions = (
        _client(oci.identity.IdentityClient)
        .list_region_subscriptions(_config()["tenancy"])
        .data
    )
    return oci.util.to_dict(subscriptions)


@cachier(separate_files=True)
def _get_availability_domains(region: str) -> list[str]:
    """List the availability domain names of a region (ListAvailabilityDomains).

    The names are specific to the tenancy, both the prefix and the mapping of
    the numbers to datacenters, e.g. `Uocm:EU-FRANKFURT-1-AD-1` or `Uocm:PHX-AD-1`.

    Reference: <https://docs.oracle.com/en-us/iaas/api/#/en/identity/20160918/AvailabilityDomain/ListAvailabilityDomains>
    """
    # example response (after `oci.util.to_dict`):
    # [
    #     {
    #         'name': 'Uocm:EU-FRANKFURT-1-AD-1',
    #         'id': 'ocid1.availabilitydomain.oc1..aaaa...',
    #         'compartment_id': 'ocid1.tenancy.oc1..aaaa...',
    #     },
    #     # ...
    # ]
    availability_domains = (
        _client(oci.identity.IdentityClient, region)
        .list_availability_domains(_config()["tenancy"])
        .data
    )
    return [availability_domain.name for availability_domain in availability_domains]


def _availability_domain(region: str, name: str) -> str:
    """Full, tenancy-specific availability domain name of a zone's API reference.

    The prefix of the tenancy is not stored in the zones, so it is looked up for
    the API calls, e.g. `EU-FRANKFURT-1-AD-1` -> `Uocm:EU-FRANKFURT-1-AD-1`.
    """
    for availability_domain in _get_availability_domains(region):
        if availability_domain.split(":")[-1] == name:
            return availability_domain
    raise KeyError(f"Unknown availability domain in {region}: {name}")


def _zone_id(region: str, availability_domain: str) -> str:
    """Zone id from the region and the tenancy-specific availability domain name.

    E.g. `Uocm:EU-FRANKFURT-1-AD-2` in eu-frankfurt-1 -> `eu-frankfurt-1-ad-2`
    and `Uocm:PHX-AD-1` in us-phoenix-1 -> `us-phoenix-1-ad-1`.
    """
    number = availability_domain.rsplit("-", 1)[-1]
    if not number.isdigit():
        raise ValueError(f"Unknown availability domain name: {availability_domain}")
    return f"{region}-ad-{number}"


@cachier(separate_files=True)
def _get_shapes(region: str, availability_domain: str) -> list[dict]:
    """List the shapes that can be launched in an availability domain (ListShapes).

    Note that only the shapes with a service limit in the tenancy are listed,
    so e.g. GPU, HPC and VM Dense I/O shapes are missing by default.

    Reference: <https://docs.oracle.com/en-us/iaas/api/#/en/iaas/20160918/Shape/ListShapes>
    """
    # example response (after `oci.util.to_dict`), unrelated fields dropped:
    # [
    #     {
    #         'shape': 'VM.Standard.E5.Flex',
    #         'processor_description': '2.3 GHz AMD EPYC™ 9J14 (Genoa)',
    #         'ocpus': 1.0,
    #         'memory_in_gbs': 12.0,
    #         'networking_bandwidth_in_gbps': 1.0,
    #         'gpus': 0,
    #         'gpu_description': None,
    #         'local_disks': 0,
    #         'local_disks_total_size_in_gbs': None,
    #         'local_disk_description': None,
    #         'rdma_ports': 0,
    #         'rdma_bandwidth_in_gbps': 0,
    #         'ocpu_options': {'min': 1.0, 'max': 126.0, 'max_per_numa_node': 94.0},
    #         'memory_options': {
    #             'min_in_g_bs': 1.0,
    #             'max_in_g_bs': 2098.0,
    #             'default_per_ocpu_in_g_bs': 12.0,
    #             'min_per_ocpu_in_gbs': 1.0,
    #             'max_per_ocpu_in_gbs': 64.0,
    #             'max_per_numa_node_in_gbs': 1049.0,
    #         },
    #         'networking_bandwidth_options': {
    #             'min_in_gbps': 1.0,
    #             'max_in_gbps': 40.0,
    #             'default_per_ocpu_in_gbps': 1.0,
    #         },
    #         'baseline_ocpu_utilizations': [
    #             'BASELINE_1_8',
    #             'BASELINE_1_2',
    #             'BASELINE_1_1',
    #         ],
    #         'platform_config_options': {'type': 'AMD_VM', ...},
    #         'is_billed_for_stopped_instance': False,
    #         'billing_type': 'PAID',
    #         'quota_names': ['standard-e5-core-count', 'standard-e5-memory-count'],
    #         'is_subcore': True,
    #         'is_flexible': True,
    #         'is_live_migration_supported': True,
    #     },
    #     {
    #         'shape': 'BM.DenseIO.E6.Ax.192',
    #         'processor_description': '2.7 GHz AMD EPYC™ 9J45 (Turin)',
    #         'ocpus': 192.0,
    #         'memory_in_gbs': 2304.0,
    #         'networking_bandwidth_in_gbps': 200.0,
    #         'gpus': 0,
    #         'gpu_description': None,
    #         'local_disks': 12,
    #         'local_disks_total_size_in_gbs': 81600.0,
    #         'local_disk_description': 'NVMe SSD Storage',
    #         'ocpu_options': None,
    #         'memory_options': None,
    #         'networking_bandwidth_options': None,
    #         'baseline_ocpu_utilizations': None,
    #         'is_billed_for_stopped_instance': True,
    #         'billing_type': 'PAID',
    #         'is_subcore': False,
    #         'is_flexible': False,
    #     },
    #     # ...
    # ]
    shapes = oci.pagination.list_call_get_all_results(
        _client(oci.core.ComputeClient, region).list_shapes,
        _config()["tenancy"],
        availability_domain=availability_domain,
    ).data
    return oci.util.to_dict(shapes)


def _shape_series(shape_name: str) -> tuple[str, str]:
    """Split a shape name into its kind (VM or BM) and series.

    E.g. VM.Standard.E5.Flex -> (VM, Standard.E5), VM.Standard2.16 -> (VM, Standard2)
    and BM.GPU.A100-v2.8 -> (BM, GPU.A100-v2).
    """
    match = _SHAPE_RE.match(shape_name)
    if not match:
        raise ValueError(f"Unknown OCI shape name format: {shape_name}")
    return match.group(1), match.group(2)


@cache
def _warn_unknown(field: str, name: str) -> None:
    """Warn about a shape with an unknown field, once per name and run."""
    logger.warning(f"Unknown OCI shape {field} of {name}, leaving {field} empty.")


def _shape_family(series: str) -> str | None:
    """Family of a shape series, e.g. Standard.E5 -> Standard, DenseIO2 -> Dense I/O.

    Returns None for unknown series, so no family is guessed.
    """
    family = _SHAPE_FAMILIES.get(series.split(".")[0].rstrip("0123456789"))
    if family is None:
        _warn_unknown("family", series)
    return family


def _is_arm(shape: dict) -> bool:
    """Check if a shape is running on the Arm-based Ampere processors."""
    if "ampere" in (shape.get("processor_description") or "").lower():
        return True
    _, series = _shape_series(shape["shape"])
    return bool(search(r"^(Standard|DenseIO)\.A\d", series))


def _vcpus_per_ocpu(shape: dict) -> int:
    """Number of vCPUs per OCPU of a shape, see `_ARM_VCPUS_PER_OCPU`."""
    if not _is_arm(shape):
        return _X86_VCPUS_PER_OCPU
    _, series = _shape_series(shape["shape"])
    generation = search(r"\.(A\d+)(?:\.|$)", series)
    if not generation or generation.group(1) not in _ARM_VCPUS_PER_OCPU:
        raise ValueError(f"Unknown OCPU definition of the Arm shape: {shape['shape']}")
    return _ARM_VCPUS_PER_OCPU[generation.group(1)]


def _parse_processor_description(description: str | None) -> dict:
    """Extract the CPU speed (GHz), manufacturer, family and model of a shape.

    E.g. `2.3 GHz AMD EPYC™ 9J14 (Genoa)` is a 2.3 GHz AMD EPYC 9J14, and
    `3.0 GHz Intel® Xeon® Gold 6354 (Ice Lake)` is a 3 GHz Intel Xeon 6354.
    When both the base and turbo frequencies are listed, the base is used.
    """
    text = (description or "").replace("®", "").replace("™", "")
    # drop the code names, e.g. (Genoa) or (Banshee 12)
    text = sub(r"\s*\([^)]*\)", "", text).strip()
    speed = search(r"([\d.]+)\s*GHz", text)
    family = None
    model = None
    if "EPYC" in text:
        family = "EPYC"
        model = search(r"EPYC\s+(\S+)", text)
    elif "Xeon" in text:
        family = "Xeon"
        model = search(r"Xeon\s+(?:(?:Platinum|Gold|Silver|Bronze)\s+)?(.+)$", text)
    elif "AmpereOne" in text:
        family = search(r"AmpereOne(?:-\w+)?", text).group(0)
    elif "Altra" in text:
        family = "Altra"
    return {
        "cpu_speed": float(speed.group(1)) if speed else None,
        "cpu_manufacturer": _extract_manufacturer(text) if text else None,
        "cpu_family": family,
        "cpu_model": model.group(1).strip() if model else None,
    }


def _flex_network_speed(shape: dict, ocpus: int) -> float | None:
    """Network bandwidth (Gbps) of a flexible shape, scaling with the OCPUs."""
    options = shape.get("networking_bandwidth_options")
    if not options or not options.get("default_per_ocpu_in_gbps"):
        return shape.get("networking_bandwidth_in_gbps")
    speed = options["default_per_ocpu_in_gbps"] * ocpus
    if options.get("min_in_gbps"):
        speed = max(speed, options["min_in_gbps"])
    if options.get("max_in_gbps"):
        speed = min(speed, options["max_in_gbps"])
    return speed


def _shape_configs(shape: dict) -> list[dict]:
    """List the server configurations of a shape.

    A fixed shape is a single configuration. Flexible shapes are expanded to a
    grid of OCPU counts (`_FLEX_OCPUS` and the maximum of the shape) and memory
    sizes (`_FLEX_MEMORY_GB_PER_VCPU`) within the limits of the shape, with the
    OCPU count and memory size (GiB) added to the server id, e.g.
    `VM.Standard.E5.Flex.4-32`. Flexible Dense I/O shapes are listed with their
    fixed configurations, see `_DENSE_IO_FLEX`.

    Configurations with more OCPUs or memory than available on a NUMA node are
    marked as extended memory instances.
    """
    name = shape["shape"]
    if not shape.get("is_flexible"):
        return [
            {
                "server_id": name,
                "ocpus": shape["ocpus"],
                "memory_gb": shape["memory_in_gbs"],
                "local_disks": shape.get("local_disks") or 0,
                "local_disks_gb": shape.get("local_disks_total_size_in_gbs") or 0,
                "network_speed": shape.get("networking_bandwidth_in_gbps"),
                "extended_memory": False,
            }
        ]

    if name in _DENSE_IO_FLEX:
        configs = []
        for ocpus in _DENSE_IO_FLEX[name]["ocpus"]:
            memory_gb = ocpus * _DENSE_IO_FLEX[name]["memory_gb_per_ocpu"]
            local_disks = ocpus // _DENSE_IO_FLEX_OCPUS_PER_DISK
            configs.append(
                {
                    "server_id": f"{name}.{ocpus}-{memory_gb}",
                    "ocpus": ocpus,
                    "memory_gb": memory_gb,
                    "local_disks": local_disks,
                    "local_disks_gb": local_disks * _DENSE_IO_FLEX_DISK_GB,
                    "network_speed": _flex_network_speed(shape, ocpus),
                    "extended_memory": False,
                }
            )
        return configs
    if shape.get("local_disks"):
        raise ValueError(f"Unknown local disk configurations of flexible shape: {name}")

    ocpu_options = shape["ocpu_options"]
    memory_options = shape["memory_options"]
    vcpus_per_ocpu = _vcpus_per_ocpu(shape)
    ocpu_min = ceil(ocpu_options["min"])
    ocpu_max = int(ocpu_options["max"])
    ocpu_grid = sorted(
        {ocpus for ocpus in _FLEX_OCPUS if ocpu_min <= ocpus <= ocpu_max} | {ocpu_max}
    )
    configs = []
    for ocpus in ocpu_grid:
        for memory_gb_per_vcpu in _FLEX_MEMORY_GB_PER_VCPU:
            memory_gb_per_ocpu = memory_gb_per_vcpu * vcpus_per_ocpu
            memory_gb = ocpus * memory_gb_per_ocpu
            if (
                memory_gb < memory_options["min_in_g_bs"]
                or memory_gb > memory_options["max_in_g_bs"]
                or memory_gb_per_ocpu < memory_options["min_per_ocpu_in_gbs"]
                or memory_gb_per_ocpu > memory_options["max_per_ocpu_in_gbs"]
            ):
                continue
            ocpu_numa_max = ocpu_options.get("max_per_numa_node")
            memory_numa_max = memory_options.get("max_per_numa_node_in_gbs")
            configs.append(
                {
                    "server_id": f"{name}.{ocpus}-{memory_gb}",
                    "ocpus": ocpus,
                    "memory_gb": memory_gb,
                    "local_disks": 0,
                    "local_disks_gb": 0,
                    "network_speed": _flex_network_speed(shape, ocpus),
                    "extended_memory": bool(
                        (ocpu_numa_max and ocpus > ocpu_numa_max)
                        or (memory_numa_max and memory_gb > memory_numa_max)
                    ),
                }
            )
    return configs


def _server_description(
    family: str | None,
    vcpus: int,
    memory_gb: float,
    storages: list[Disk],
    gpu_count: int = 0,
    gpu_model: str | None = None,
    gpu_vram_gb: float | None = None,
) -> str:
    nvme_size = sum(d.size for d in storages if d.storage_type == StorageType.NVME_SSD)
    ssd_size = sum(d.size for d in storages if d.storage_type == StorageType.SSD)
    description_parts = [
        f"{vcpus} vCPUs",
        f"{memory_gb:g} GiB RAM",
        f"{nvme_size} GB NVMe" if nvme_size else None,
        f"{ssd_size} GB SSD" if ssd_size else None,
        (
            f"{gpu_count}x{gpu_model} {gpu_vram_gb:g} GiB VRAM"
            if gpu_count and gpu_model and gpu_vram_gb
            else (f"{gpu_count}x{gpu_model}" if gpu_count and gpu_model else None)
        ),
    ]
    description_parts_str = ", ".join(filter(None, description_parts))
    return f"{family} ({description_parts_str})" if family else description_parts_str


def _shape_servers(shape: dict, vendor) -> list[dict]:
    """Convert a shape to the list of its server configurations."""
    name = shape["shape"]
    kind, series = _shape_series(name)
    family = _shape_family(series)
    is_arm = _is_arm(shape)
    vcpus_per_ocpu = _vcpus_per_ocpu(shape)
    cpu = _parse_processor_description(shape.get("processor_description"))

    gpu_count = shape.get("gpus") or 0
    gpu = {}
    if gpu_count:
        gpu = _GPU_SERIES.get(series, {})
        if not gpu:
            _warn_unknown("GPU model", name)
    gpu_description = shape.get("gpu_description") or ""
    gpu_manufacturer = gpu.get("manufacturer") or (
        (_extract_manufacturer(gpu_description) or "NVIDIA") if gpu_count else None
    )
    gpu_vram_gb = gpu.get("vram_gb")

    is_nvme = "nvme" in (shape.get("local_disk_description") or "").lower()
    storage_type = StorageType.NVME_SSD if is_nvme else StorageType.SSD

    items = []
    for config in _shape_configs(shape):
        ocpus = config["ocpus"]
        vcpus = int(ocpus * vcpus_per_ocpu)
        memory_gb = config["memory_gb"]
        storages = [
            Disk(
                size=int(config["local_disks_gb"] / config["local_disks"]),
                storage_type=storage_type,
            )
            for _ in range(config["local_disks"])
        ]
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "server_id": config["server_id"],
                "name": config["server_id"],
                "api_reference": name,
                # https://www.pulumi.com/registry/packages/oci/api-docs/core/instance/
                "api_reference_object": (
                    {
                        "shape": name,
                        "shape_config": {"ocpus": ocpus, "memory_in_gbs": memory_gb},
                    }
                    if shape.get("is_flexible")
                    else {"shape": name}
                ),
                "display_name": config["server_id"],
                "description": _server_description(
                    f"Bare Metal {family}" if family and kind == "BM" else family,
                    vcpus,
                    memory_gb,
                    storages,
                    gpu_count,
                    gpu.get("model"),
                    gpu_vram_gb,
                ),
                "family": family,
                "series": series,
                "vcpus": vcpus,
                "hypervisor": None,
                # OCPUs are dedicated physical cores, except for the Always Free
                # micro shape with 1/8 OCPU and the ability to burst
                "cpu_allocation": (
                    CpuAllocation.BURSTABLE
                    if name.endswith(".Micro")
                    else CpuAllocation.DEDICATED
                ),
                "cpu_cores": int(ocpus * (vcpus_per_ocpu if is_arm else 1)),
                "cpu_speed": cpu["cpu_speed"],
                "cpu_architecture": (
                    CpuArchitecture.ARM64 if is_arm else CpuArchitecture.X86_64
                ),
                "cpu_manufacturer": cpu["cpu_manufacturer"],
                "cpu_family": cpu["cpu_family"],
                "cpu_model": cpu["cpu_model"],
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
                "memory_amount": int(memory_gb * _MIB_PER_GIB),
                "memory_generation": None,
                "memory_speed": None,
                "memory_ecc": None,
                "accelerator_count": gpu_count,
                "accelerator_memory_min": (
                    int(gpu_vram_gb * _MIB_PER_GIB) if gpu_vram_gb else None
                ),
                "accelerator_memory_total": (
                    int(gpu_vram_gb * gpu_count * _MIB_PER_GIB) if gpu_vram_gb else None
                ),
                "accelerator_type": AcceleratorType.GPU if gpu_count else None,
                "accelerator_manufacturer": gpu_manufacturer,
                "accelerator_family": gpu.get("family"),
                "accelerator_model": gpu.get("model"),
                "accelerators": [],
                "storage_size": sum(disk.size for disk in storages),
                "storage_type": storage_type if storages else None,
                "storages": storages,
                # block volumes can be attached to all VM and bare metal shapes
                "compatible_storage_ids": list(_BLOCK_VOLUMES),
                "network_speed_baseline": None,
                # documented as the "Max Network Bandwidth" of the shapes
                "network_speed_max": config["network_speed"],
                "network_storage_speed_baseline": None,
                "network_storage_speed_max": None,
                # the free outbound traffic is per tenancy (see inventory_traffic_prices)
                "inbound_traffic": 0,
                "outbound_traffic": 0,
                # public IPv4 addresses are free of charge (see inventory_ipv4_prices)
                "ipv4": 1,
                "status": (
                    Status.INACTIVE
                    if shape.get("billing_type") == "ALWAYS_FREE"
                    else Status.ACTIVE
                ),
            }
        )
    return items


@cachier()
def _get_price_list() -> list[dict]:
    """List the products of the public Oracle Cloud price list in USD.

    The prices are the same in all commercial regions.

    Reference: <https://docs.oracle.com/en-us/iaas/Content/GSG/Tasks/signingup_topic-Estimating_Costs.htm>
    """
    # example response:
    # {
    #     'lastUpdated': '2026-11-02T14:49:49.342Z',
    #     'items': [
    #         {
    #             'partNumber': 'B97384',
    #             'displayName': 'Compute - Standard - E5 - OCPU',
    #             'metricName': 'OCPU Per Hour',
    #             'serviceCategory': 'Compute - Virtual Machine',
    #             'currencyCodeLocalizations': [
    #                 {
    #                     'currencyCode': 'USD',
    #                     'prices': [{'model': 'PAY_AS_YOU_GO', 'value': 0.03}],
    #                 },
    #             ],
    #         },
    #         {
    #             'partNumber': 'B93297',
    #             'displayName': 'Compute - Standard - A1 - OCPU',
    #             'metricName': 'OCPU Per Hour',
    #             'serviceCategory': 'Compute - Virtual Machine',
    #             'currencyCodeLocalizations': [
    #                 {
    #                     'currencyCode': 'USD',
    #                     'prices': [
    #                         {
    #                             'model': 'PAY_AS_YOU_GO',
    #                             'value': 0,
    #                             'rangeMin': 0,
    #                             'rangeMax': 3000,
    #                         },
    #                         {
    #                             'model': 'PAY_AS_YOU_GO',
    #                             'value': 0.01,
    #                             'rangeMin': 3000,
    #                             'rangeMax': 999999999999999,
    #                         },
    #                     ],
    #                 },
    #             ],
    #         },
    #         # ...
    #     ],
    # }
    response = get(
        _PRICE_LIST_URL, params={"currencyCode": "USD"}, timeout=_API_TIMEOUT
    )
    response.raise_for_status()
    return response.json()["items"]


@cache
def _price_parts() -> dict[str, dict]:
    """Products of the price list by part number."""
    return {item["partNumber"]: item for item in _get_price_list()}


def _part_price_tiers(part_number: str) -> list[dict]:
    """Pay as you go price tiers of a part in USD, ordered by the usage range."""
    part = _price_parts()[part_number]
    prices = [
        price
        for localization in part["currencyCodeLocalizations"]
        if localization["currencyCode"] == "USD"
        for price in localization["prices"]
        if price["model"] == "PAY_AS_YOU_GO"
    ]
    if not prices:
        raise KeyError(f"No pay as you go USD price found for OCI part {part_number}")
    return sorted(prices, key=lambda price: price.get("rangeMin") or 0)


def _part_price(part_number: str) -> float:
    """Pay as you go price of a part in USD, ignoring the free tier (if any)."""
    return _part_price_tiers(part_number)[-1]["value"]


@cache
def _warn_no_price(shape_name: str) -> None:
    """Warn about a shape without known price parts, once per shape and run."""
    logger.warning(
        f"No known price list parts for the OCI shape {shape_name}, skipping prices."
    )


def _shape_price_parts(shape_name: str) -> dict[str, str] | None:
    """Price list parts of a shape, see `_SHAPE_PRICE_PARTS`."""
    kind, series = _shape_series(shape_name)
    return _SHAPE_PRICE_PARTS.get(f"{kind}.{series}") or _SHAPE_PRICE_PARTS.get(series)


def _config_hourly_price(shape: dict, config: dict) -> float | None:
    """Hourly on-demand price of a server configuration of a shape.

    Returns None when the price list parts of the shape are not known.
    """
    parts = _shape_price_parts(shape["shape"])
    if parts is None:
        _warn_no_price(shape["shape"])
        return None
    if "gpu" in parts:
        return shape["gpus"] * _part_price(parts["gpu"])
    price = config["ocpus"] * _part_price(parts["ocpu"])
    if "memory" in parts:
        price += config["memory_gb"] * _part_price(parts["memory"])
    if "nvme" in parts:
        price += config["local_disks_gb"] / 1000 * _part_price(parts["nvme"])
    return price


def _inventory_server_prices(vendor, allocation: Allocation) -> list[dict]:
    """List the server prices of all active zones for an allocation type."""
    items = []
    zones = [zone for zone in vendor.zones if zone.status == Status.ACTIVE]
    vendor.progress_tracker.start_task(
        name=f"Searching {allocation.value} server prices", total=len(zones)
    )
    for zone in zones:
        availability_domain = _availability_domain(zone.region_id, zone.api_reference)
        for shape in _get_shapes(zone.region_id, availability_domain):
            with sentry_capture_or_raise(vendor=vendor):
                # limited to two instances per tenancy, see inventory_servers
                if shape.get("billing_type") == "ALWAYS_FREE":
                    continue
                kind, series = _shape_series(shape["shape"])
                is_spot = allocation == Allocation.SPOT
                if is_spot and (kind != "VM" or series not in _PREEMPTIBLE_SERIES):
                    continue
                for config in _shape_configs(shape):
                    if is_spot and config["extended_memory"]:
                        continue
                    price = _config_hourly_price(shape, config)
                    if price is None:
                        break
                    if is_spot:
                        price *= 1 - _PREEMPTIBLE_DISCOUNT
                    items.append(
                        {
                            "vendor_id": vendor.vendor_id,
                            "region_id": zone.region_id,
                            "zone_id": zone.zone_id,
                            "server_id": config["server_id"],
                            "operating_system": "Linux",
                            "allocation": allocation,
                            "unit": PriceUnit.HOUR,
                            "price": price,
                            "price_upfront": 0,
                            "price_tiered": [],
                            "currency": "USD",
                        }
                    )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return items


def inventory_compliance_frameworks(vendor):
    """Manual list of known compliance frameworks at Oracle Cloud Infrastructure.

    Data sources:

    - <https://www.oracle.com/corporate/cloud-compliance/>
    - <https://blogs.oracle.com/cloud-infrastructure/fall-2022-compliance-attestations>
    """
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id,
        [
            "hipaa",
            "soc2t2",
            "iso27001",
        ],
    )


def inventory_regions(vendor):
    """List all regions of the commercial realm.

    The API returns the identifier and key of the regions only, so the
    location is looked up from a manual mapping based on
    <https://docs.oracle.com/en-us/iaas/Content/General/Concepts/regions.htm>.

    Availability domains and shapes can be listed only in the regions the
    tenancy is subscribed to, so the other regions are stored as INACTIVE.
    """
    items = []
    subscribed = {
        subscription["region_name"]
        for subscription in _get_region_subscriptions()
        if subscription["status"] == "READY"
    }
    not_subscribed = []
    for region in _get_regions():
        with sentry_capture_or_raise(vendor=vendor):
            region_id = region["name"]
            if region_id not in _REGION_LOCATIONS:
                raise KeyError(f"Unknown OCI region without location: {region_id}")
            location = _REGION_LOCATIONS[region_id]
            if region_id not in subscribed:
                not_subscribed.append(region_id)
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region_id,
                    "name": location["name"],
                    "api_reference": region_id,
                    "display_name": location["name"],
                    "aliases": [region["key"]],
                    "country_id": location["country_id"],
                    "state": location.get("state"),
                    "city": location["city"],
                    "address_line": None,
                    "zip_code": None,
                    "lon": location["lon"],
                    "lat": location["lat"],
                    "founding_year": location.get("founding_year"),
                    "green_energy": location.get("green_energy"),
                    "status": (
                        Status.ACTIVE if region_id in subscribed else Status.INACTIVE
                    ),
                }
            )
    if not_subscribed:
        logger.warning(
            f"The OCI tenancy is not subscribed to {len(not_subscribed)} regions "
            f"(e.g. {', '.join(not_subscribed[:5])}), storing those as inactive "
            "without zones and servers."
        )
    return items


def inventory_zones(vendor):
    """List the availability domains of the subscribed regions as zones.

    The availability domain names (e.g. `Uocm:EU-FRANKFURT-1-AD-1`) are specific
    to the tenancy, so the zone id is built from the region and the number of
    the availability domain, and the name is stored without the prefix of the
    tenancy (see `_availability_domain` for looking up the full name).
    Note that the numbers are also mapped to the datacenters per tenancy, so
    e.g. AD-1 can be a different datacenter in another tenancy.

    Fault domains are not listed as zones.
    """
    items = []
    regions = [region for region in vendor.regions if region.status == Status.ACTIVE]
    vendor.progress_tracker.start_task(name="Fetching zones", total=len(regions))
    for region in regions:
        for availability_domain in _get_availability_domains(region.api_reference):
            name = availability_domain.split(":")[-1]
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "zone_id": _zone_id(region.region_id, availability_domain),
                    "name": name,
                    "api_reference": name,
                    "display_name": name,
                }
            )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return items


def inventory_servers(vendor):
    """List all shapes of the active zones as servers.

    Shapes are listed per availability domain, as the offers differ. Fixed
    shapes are stored as a server, while flexible shapes are expanded to a
    grid of OCPU and memory configurations, each stored as a separate server
    (see `_shape_configs`). Burstable configurations (a baseline of 12.5% or
    50% of the OCPUs) are not listed.

    Lifecycle: shapes listed in any of the active zones -> ACTIVE, except for
    the Always Free micro shape (limited to two instances per tenancy) ->
    INACTIVE. There is no lifecycle field or retirement date in the API, and
    the previous generation shapes (past their "end of orderability" date) are
    still fully supported and can be launched as per
    <https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm#previous-generation-shapes>,
    so those are ACTIVE as well.
    """
    zone_regions = {zone.api_reference: zone.region_id for zone in vendor.zones}

    def _search_servers(zone_name: str) -> list[dict]:
        servers = []
        region = zone_regions[zone_name]
        availability_domain = _availability_domain(region, zone_name)
        for shape in _get_shapes(region, availability_domain):
            with sentry_capture_or_raise(vendor=vendor):
                servers.extend(_shape_servers(shape, vendor))
        return servers

    return parallel_fetch_servers(vendor, _search_servers, "server_id", "zones")


def inventory_server_prices(vendor):
    """List the on-demand price of the servers in all active zones.

    The availability of the shapes is from the API (per availability domain),
    while the prices are from the public price list, which is the same in all
    commercial regions and has no reference to the shapes, so the related parts
    are looked up from a manual mapping (see `_SHAPE_PRICE_PARTS`). Shapes
    without known parts are logged and listed without prices.

    Notes:

    - The monthly free tier of the Arm-based A1 shapes (3,000 OCPU and 18,000 GB
      hours) is per tenancy, so it is not applied.
    - Only Linux prices are listed (no license fee for Oracle Linux and the
      other free images).
    """
    return _inventory_server_prices(vendor, Allocation.ONDEMAND)


def inventory_server_prices_spot(vendor):
    """List the preemptible price of the servers in all active zones.

    There is no spot market at OCI: preemptible capacity has a fixed 50%
    discount on the on-demand price in all regions, and is available only for
    the VM shapes listed in `_PREEMPTIBLE_SERIES`, as per
    <https://docs.oracle.com/en-us/iaas/Content/Compute/Concepts/preemptible.htm>.
    """
    return _inventory_server_prices(vendor, Allocation.SPOT)


def inventory_storages(vendor):
    """List the performance levels of the Block Volume service as storages.

    There is no API to list the performance levels, so these are from a
    manual list (see `_BLOCK_VOLUMES`).

    Data sources:

    - <https://docs.oracle.com/en-us/iaas/Content/Block/Concepts/blockvolumeperformance.htm>
    - <https://www.oracle.com/cloud/storage/block-volumes/faq/>

    Sizes are in GB, and throughput values are in MB/s as per the documentation.
    """
    items = []
    for storage_id, storage in _BLOCK_VOLUMES.items():
        items.append(
            {
                "storage_id": storage_id,
                "vendor_id": vendor.vendor_id,
                "name": storage["name"],
                "description": storage["description"],
                "storage_type": StorageType.NVME_SSD,
                "max_iops": storage["max_iops"],
                "max_throughput": storage["max_throughput"],
                "min_size": _BLOCK_VOLUME_MIN_SIZE,
                "max_size": _BLOCK_VOLUME_MAX_SIZE,
            }
        )
    return items


def inventory_storage_prices(vendor):
    """List the Block Volume prices in all regions.

    The monthly price of a GB is the storage price plus the price of the
    Volume Performance Units (VPU) of the performance level, both from the
    public price list, which is the same in all commercial regions.
    """
    storage_price = _part_price(_BLOCK_VOLUME_STORAGE_PART)
    vpu_price = _part_price(_BLOCK_VOLUME_VPU_PART)
    items = []
    for region in vendor.regions:
        for storage_id, storage in _BLOCK_VOLUMES.items():
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "storage_id": storage_id,
                    "unit": PriceUnit.GB_MONTH,
                    "price": storage_price + storage["vpus"] * vpu_price,
                    "currency": "USD",
                }
            )
    return items


def _price_tiers(part_number: str) -> list[dict]:
    """Convert the usage ranges of a price list part to tiered prices."""
    tiers = _part_price_tiers(part_number)
    if len(tiers) < 2:
        return []
    return [
        {
            "lower": tier["rangeMin"] + 1,
            "upper": (
                "Infinity"
                if tier["rangeMax"] >= _PRICE_RANGE_INFINITY
                else tier["rangeMax"]
            ),
            "price": tier["value"],
        }
        for tier in tiers
    ]


def inventory_traffic_prices(vendor):
    """List the inbound and outbound traffic prices in all regions.

    Inbound traffic is free. The first 10 TB of outbound traffic is free per
    month and tenancy, then priced per GB depending on the location of the
    region (see `_EGRESS_PARTS`), as per the public price list.
    """
    items = []
    for region in vendor.regions:
        with sentry_capture_or_raise(vendor=vendor):
            part_number = _EGRESS_PARTS[region.region_id.split("-")[0]]
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
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
                    "region_id": region.region_id,
                    "price": _part_price(part_number),  # max tier price
                    "price_tiered": _price_tiers(part_number),
                    "currency": "USD",
                    "unit": PriceUnit.GB_MONTH,
                    "direction": TrafficDirection.OUT,
                }
            )
    return items


def inventory_ipv4_prices(vendor):
    """Public IPv4 addresses are free of charge at OCI.

    Neither ephemeral, nor reserved public IP addresses are charged: there is
    no related part in the public price list, and "there is no charge to use
    this feature" as per the announcement of the reserved public IPs at
    <https://blogs.oracle.com/cloud-infrastructure/release-announcement-reserved-public-ips-are-now-available-on-oracle-cloud-infrastructure>.
    """
    items = []
    for region in vendor.regions:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "price": 0,
                "currency": "USD",
                "unit": PriceUnit.MONTH,
            }
        )
    return items


# TODO: Implement database collectors (OCI Database with PostgreSQL)


def inventory_databases(vendor):
    return []


def inventory_database_prices(vendor):
    return []


def inventory_database_storages(vendor):
    return []


def inventory_database_storage_prices(vendor):
    return []
