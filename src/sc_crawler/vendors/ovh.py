from functools import cache
from os import environ, getenv
from typing import Optional

from ovh import Client

from ..lookup import map_compliance_frameworks_to_vendor
from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)
from ..utils import scmodels_to_dict

HOURS_PER_MONTH = 730
MICROCENTS_PER_CURRENCY_UNIT = 100_000_000
MIB_PER_GIB = 1024


@cache
def _client() -> Client:
    """Create an OVHcloud API client using a service account via OAuth2.

    Note that the classic API authentication flow with user approval is not
    supported due to its short token expiration and the need for user
    interaction.

    Environment variables required:
    - `OVH_ENDPOINT`: API endpoint (e.g. ovh-eu)
    - `OVH_CLIENT_ID`
    - `OVH_CLIENT_SECRET`
    """
    for ev in ["OVH_ENDPOINT", "OVH_CLIENT_ID", "OVH_CLIENT_SECRET"]:
        if ev not in environ:
            raise KeyError(f"Missing environment variable: {ev}")
    return Client()


@cache
def _get_project_id() -> str:
    """Get project ID from environment or first available project.

    Returns:
        str: Project ID from OVH_PROJECT_ID env var or first project in account.

    Raises:
        RuntimeError: If no projects defined as environment variable or found in OVHcloud account.
    """
    project_id = getenv("OVH_PROJECT_ID")
    if project_id:
        return project_id.strip()

    # fall back to first project in account (if any)
    projects = _client().get("/cloud/project")
    if not projects:
        raise RuntimeError("No projects defined/found in OVHcloud account")
    return projects[0]


@cache
def _get_regions(project_id: Optional[str] = None) -> list[str]:
    """Fetch available regions enabled for a project.

    The catalogue-based region extraction is preferred over this function in
    general, as it's more complete: not all regions might be enabled for a
    project.

    Args:
        project_id: Project ID to use for listing regions. Defaults to the first project in the account if not provided.

    Returns:
        List of region codes
    """
    project_id = project_id or _get_project_id()
    try:
        return _client().get(f"/cloud/project/{project_id}/region")
    except Exception as e:
        raise Exception(f"Failed to fetch regions for project {project_id}: {e}") from e


@cache
def _get_region(region_name: str, project_id: Optional[str] = None) -> dict:
    """Fetch region details.

    Args:
        region_name: Name of the region to fetch details for.
        project_id: Project ID to use for listing regions. Defaults to the first project in the account if not provided.

    Returns:
        Region dictionary.
    """
    project_id = project_id or _get_project_id()
    return _client().get(f"/cloud/project/{project_id}/region/{region_name}")


@cache
def _get_catalog(subsidiary: str = getenv("OVH_SUBSIDIARY", "IE")) -> dict:
    """Fetch service catalog.

    Args:
        subsidiary: OVH subsidiary to use for fetching the public catalog.

    Returns:
        Catalog dictionary with plans and addons.
    """
    return _client().get("/order/catalog/public/cloud", ovhSubsidiary=subsidiary)


def _get_server_family(instance_type_name: str) -> str | None:
    """Map OVHcloud instance type name to server family.

    Server families are displayed on the pricing page:
    https://www.ovhcloud.com/en/public-cloud/prices/ (retrieved 2025-11-19)

    Returns:
        str: Server family name (e.g., "General Purpose", "Compute Optimized")
    """
    name_lower = instance_type_name.lower()

    # Extract prefix (e.g., 'b2-7' -> 'b2', 't1-45' -> 't1')
    prefix = name_lower.split("-")[0]

    # GPU instances
    if prefix in ["t1", "t2", "a10", "a100", "l4", "l40s", "h100", "rtx5000"]:
        return "Cloud GPU"

    # Metal instances
    if prefix == "bm":
        return "Metal"

    # General Purpose: b2, b3 families
    if prefix in ["b2", "b3"]:
        return "General Purpose"

    # Compute Optimized: c2, c3 families
    if prefix in ["c2", "c3"]:
        return "Compute Optimized"

    # Memory Optimized: r2, r3 families
    if prefix in ["r2", "r3"]:
        return "Memory Optimized"

    # Discovery: d2 family
    if prefix == "d2":
        return "Discovery"

    # Storage Optimized: i1 family
    if prefix == "i1":
        return "Storage Optimized"

    # Default fallback
    return None


def _get_gpu_info(
    flavor_name: str,
) -> tuple[int, int | None, str | None, str | None, str | None]:
    """Map GPU flavor name to GPU specs based on verified data.

    GPU Memory Specifications (retrieved 2025-11-19):
    OVHcloud Prices Page: https://www.ovhcloud.com/en/public-cloud/prices/
    OVHcloud Product Page: https://www.ovhcloud.com/en/public-cloud/gpu/
    - A10: 24GB GDDR6
    - Quadro RTX 5000: 16GB GDDR6
    - Tesla V100: 16GB HBM2
    - Tesla V100S: 32GB HBM2
    - L4: 24GB GDDR6
    - L40S: 48GB GDDR6
    - H100: 80GB HBM3
    - A100: 80GB HBM2e

    GPU Architecture Information (retrieved 2025-11-19):
    Source: NVIDIA Official Product Pages and Architecture Whitepapers
    - H100: Hopper Architecture - https://www.nvidia.com/en-us/data-center/h100/
    - A100: Ampere Architecture - https://www.nvidia.com/en-us/data-center/a100/
    - A10: Ampere Architecture - https://www.nvidia.com/en-us/data-center/products/a10-gpu/
    - L40S: Ada Lovelace Architecture - https://www.nvidia.com/en-us/data-center/l40s/
    - L4: Ada Lovelace Architecture - https://www.nvidia.com/en-us/data-center/l4/
    - Tesla V100/V100S: Volta Architecture - https://www.nvidia.com/en-us/data-center/v100/
    - Quadro RTX 5000: Turing Architecture - https://www.nvidia.com/en-us/design-visualization/quadro/rtx-5000/

    Instance Specifications (from OVHcloud Cloud Manager, retrieved 2025-11-19):
    GPU counts per instance type and system configurations (vCores, RAM, storage)
    are documented in individual GPU mapping comments below.

    Returns:
        tuple: (gpu_count, gpu_memory_total, gpu_manufacturer, gpu_family, gpu_model)
               or (0, None, None, None, None) if not a GPU instance
    """
    name_lower = flavor_name.lower()

    # Parse GPU instance naming pattern: <gpu_model>-<instance_size>

    # NVIDIA H100 (80GB HBM3 per GPU) - Hopper Architecture
    # OVHcloud instances (source: OVHcloud Cloud Manager, 2025-11-19):
    # - h100-380: 1x H100, 380 GB RAM, 30 vCores (3 GHz), 200 GB + 3.84 TB NVMe Passthrough, 8,000 Mbit/s
    # - h100-760: 2x H100, 760 GB RAM, 60 vCores (3 GHz), 200 GB + 2x 3.84 TB NVMe Passthrough, 16,000 Mbit/s
    # - h100-1520: 4x H100, 1,520 GB RAM, 120 vCores (3 GHz), 200 GB + 4x 3.84 TB NVMe Passthrough, 25,000 Mbit/s
    if name_lower.startswith("h100-"):
        try:
            size = int(name_lower.split("-")[1])
            gpu_count = size // 380
            return gpu_count, gpu_count * 80 * MIB_PER_GIB, "NVIDIA", "Hopper", "H100"
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA A100 (80GB HBM2e per GPU) - Ampere Architecture
    # - a100-180: 1x A100, 180 GB RAM, 15 vCores, 300 GB NVMe, 8,000 Mbit/s
    # - a100-360: 2x A100, 360 GB RAM, 30 vCores, 500 GB NVMe, 16,000 Mbit/s
    # - a100-720: 4x A100, 720 GB RAM, 60 vCores, 500 GB NVMe, 25,000 Mbit/s
    if name_lower.startswith("a100-"):
        try:
            size = int(name_lower.split("-")[1])
            gpu_count = size // 180
            return gpu_count, gpu_count * 80 * MIB_PER_GIB, "NVIDIA", "Ampere", "A100"
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA A10 Tensor Core GPU (24GB GDDR6 per GPU) - Ampere Architecture
    # OVHcloud instances:
    # - a10-45: 1x A10, 45 GB RAM, 30 vCores (3.3 GHz), 400 GB SSD, 8,000 Mbit/s
    # - a10-90: 2x A10, 90 GB RAM, 60 vCores (3.3 GHz), 400 GB SSD, 16,000 Mbit/s
    # - a10-180: 4x A10, 180 GB RAM, 120 vCores (3.3 GHz), 400 GB SSD, 25,000 Mbit/s
    if name_lower.startswith("a10-"):
        try:
            size = int(name_lower.split("-")[1])
            gpu_count = size // 45
            return gpu_count, gpu_count * 24 * MIB_PER_GIB, "NVIDIA", "Ampere", "A10"
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA L40S (48GB GDDR6 per GPU) - Ada Lovelace Architecture
    # OVHcloud instances:
    # - l40s-90: 1x L40S, 90 GB RAM, 15 vCores (2.75 GHz), 400 GB NVMe, 8,000 Mbit/s
    # - l40s-180: 2x L40S, 180 GB RAM, 30 vCores (2.75 GHz), 400 GB NVMe, 16,000 Mbit/s
    # - l40s-360: 4x L40S, 360 GB RAM, 60 vCores (2.75 GHz), 400 GB NVMe, 25,000 Mbit/s
    if name_lower.startswith("l40s-"):
        try:
            size = int(name_lower.split("-")[1])
            gpu_count = size // 90
            return (
                gpu_count,
                gpu_count * 48 * MIB_PER_GIB,
                "NVIDIA",
                "Ada Lovelace",
                "L40S",
            )
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA L4 Tensor Core GPU (24GB GDDR6 per GPU) - Ada Lovelace Architecture
    # OVHcloud instances:
    # - l4-90: 1x L4, 90 GB RAM, 22 vCores (2.75 GHz), 400 GB NVMe, 8,000 Mbit/s
    # - l4-180: 2x L4, 180 GB RAM, 45 vCores (2.75 GHz), 400 GB NVMe, 16,000 Mbit/s
    # - l4-360: 4x L4, 360 GB RAM, 90 vCores (2.75 GHz), 400 GB NVMe, 25,000 Mbit/s
    if name_lower.startswith("l4-"):
        try:
            size = int(name_lower.split("-")[1])
            gpu_count = size // 90
            return (
                gpu_count,
                gpu_count * 24 * MIB_PER_GIB,
                "NVIDIA",
                "Ada Lovelace",
                "L4",
            )
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA Tesla V100S (32GB HBM2 per GPU) - Volta Architecture
    # OVHcloud instances - Standard series:
    # - t2-45: 1x V100S, 45 GB RAM, 15 vCores (2.9 GHz), 400 GB NVMe, 2,000 Mbit/s
    # - t2-90: 2x V100S, 90 GB RAM, 30 vCores (2.9 GHz), 800 GB NVMe, 4,000 Mbit/s
    # - t2-180: 4x V100S, 180 GB RAM, 60 vCores (2.9 GHz), 50 GB + 2x 2 TB NVMe Passthrough, 10,000 Mbit/s
    # OVHcloud instances - Limited Edition (LE) series:
    # - t2-le-45: 1x V100S, 45 GB RAM, 15 vCores (2.9 GHz), 300 GB NVMe, 2,000 Mbit/s
    # - t2-le-90: 2x V100S, 90 GB RAM, 30 vCores (2.9 GHz), 500 GB NVMe, 4,000 Mbit/s
    # - t2-le-180: 4x V100S, 180 GB RAM, 60 vCores (2.9 GHz), 500 GB NVMe, 10,000 Mbit/s
    if name_lower.startswith("t2-") or name_lower.startswith("t2-le-"):
        try:
            # Extract size: 't2-45' -> 45, 't2-le-45' -> 45
            parts = name_lower.split("-")
            size = int(parts[-1])
            gpu_count = size // 45
            return gpu_count, gpu_count * 32 * MIB_PER_GIB, "NVIDIA", "Volta", "V100S"
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA Tesla V100 (16GB HBM2 per GPU) - Volta Architecture
    # OVHcloud instances - Standard series:
    # - t1-45: 1x V100, 45 GB RAM, 8 vCores (3 GHz), 400 GB NVMe, 2,000 Mbit/s
    # - t1-90: 2x V100, 90 GB RAM, 18 vCores (3 GHz), 800 GB NVMe, 4,000 Mbit/s
    # - t1-180: 4x V100, 180 GB RAM, 36 vCores (3 GHz), 50 GB + 2x 2 TB NVMe Passthrough, 10,000 Mbit/s
    # OVHcloud instances - Limited Edition (LE) series:
    # - t1-le-45: 1x V100, 45 GB RAM, 8 vCores (3 GHz), 300 GB NVMe, 2,000 Mbit/s
    # - t1-le-90: 2x V100, 90 GB RAM, 16 vCores (3 GHz), 400 GB NVMe, 4,000 Mbit/s
    # - t1-le-180: 4x V100, 180 GB RAM, 32 vCores (3 GHz), 400 GB NVMe, 10,000 Mbit/s
    if name_lower.startswith("t1-") or name_lower.startswith("t1-le-"):
        try:
            # Extract size: 't1-45' -> 45, 't1-le-45' -> 45
            parts = name_lower.split("-")
            size = int(parts[-1])
            gpu_count = size // 45
            return gpu_count, gpu_count * 16 * MIB_PER_GIB, "NVIDIA", "Volta", "V100"
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA Quadro RTX 5000 (16GB GDDR6 per GPU) - Turing Architecture
    # OVHcloud instances:
    # - rtx5000-28: 1x Quadro RTX 5000, 28 GB RAM, 4 vCores (3.3 GHz), 400 GB SSD, 2,000 Mbit/s
    # - rtx5000-56: 2x Quadro RTX 5000, 56 GB RAM, 8 vCores (3.3 GHz), 400 GB SSD, 4,000 Mbit/s
    # - rtx5000-84: 3x Quadro RTX 5000, 84 GB RAM, 16 vCores (3.3 GHz), 400 GB SSD, 10,000 Mbit/s
    if name_lower.startswith("rtx5000-"):
        try:
            size = int(name_lower.split("-")[1])
            gpu_count = size // 28
            return (
                gpu_count,
                gpu_count * 16 * MIB_PER_GIB,
                "NVIDIA",
                "Turing",
                "Quadro RTX 5000",
            )
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # Not a GPU instance
    return 0, None, None, None, None


def inventory_compliance_frameworks(vendor):
    """Manual list of known compliance frameworks on OVHcloud.

    Data sources:

    - General information and list of supported compliance programs: <https://www.ovhcloud.com/en/compliance/>
    - ISO/IEC 27001/27017/27018: <https://www.ovhcloud.com/en/compliance/iso-27001-27017-27018/>
    - SOC 1, SOC 2, SOC 3 with SOC 2 Type 2 details: <https://www.ovhcloud.com/en/compliance/soc-1-2-3/>
    """
    # Additional OVHcloud compliance frameworks you may want to support later
    # (not yet present in lookup.py — listed here for reference only):
    #   - ISO/IEC 27017 (cloud security controls)
    #       URL: https://www.ovhcloud.com/en/compliance/iso-27001-27017-27018/
    #       Suggested ID: "iso27017"
    #   - ISO/IEC 27018 (protection of PII in public cloud)
    #       URL: https://www.ovhcloud.com/en/compliance/iso-27001-27017-27018/
    #       Suggested ID: "iso27018"
    #   - SOC 1 (SSAE18 Type 2)
    #       URL: https://www.ovhcloud.com/en/compliance/soc-1-2-3/
    #       Suggested ID: "soc1t2"
    #   - SOC 3 (general report)
    #       URL: https://www.ovhcloud.com/en/compliance/soc-1-2-3/
    #       Suggested ID: "soc3"
    #   - PCI DSS (payment card industry data security standard)
    #       URL: https://www.ovhcloud.com/en/compliance/pci-dss/
    #       Suggested ID: "pci-dss"
    #   - HDS (Hébergement de Données de Santé / Healthcare data hosting compliance)
    #       URL: https://www.ovhcloud.com/en/compliance/hds/
    #       Suggested ID: "hds"
    #   - ANSSI SecNumCloud (France national cloud security label)
    #       URL: https://www.ovhcloud.com/en/compliance/secnumcloud/
    #       Suggested ID: "secnumcloud"
    #   - ISO 14001 (environmental management systems — non-security but published by OVHcloud)
    #       URL: https://www.ovhcloud.com/en/compliance/iso-14001/
    #       Suggested ID: "iso14001"
    return map_compliance_frameworks_to_vendor(vendor.vendor_id, ["iso27001", "soc2t2"])


def inventory_regions(vendor) -> list[dict]:
    """List all available OVHcloud Public Cloud regions.

    Data sources:

    - <https://www.ovhcloud.com/en/public-cloud/regions-availability/>
    - <https://www.ovhcloud.com/en/about-us/global-infrastructure/expansion-regions-az/>
    - <https://vms.status-ovhcloud.com/>
    - Google Maps search for the datacenter location or city-level coordinates
    """
    items = []
    regions = _get_regions()
    datacenters = {
        # Europe (EMEA)
        "SBG": {
            "country_id": "FR",
            "city": "Strasbourg",
            "address_line": "9 Rue du Bass. de l'Industrie",
            "zip_code": "67000",
            "lat": 48.5854388,
            "lon": 7.7974307,
        },
        "GRA": {
            "country_id": "FR",
            "city": "Gravelines",
            "address_line": "1 Rte de la Frm Masson",
            "zip_code": "59820",
            "lat": 51.0166852,
            "lon": 2.1551437,
        },
        "RBX": {
            "country_id": "FR",
            "city": "Roubaix",
            "address_line": "2 Rue Kellermann",
            "zip_code": "59100",
            "lat": 50.691834,
            "lon": 3.2003148,
        },
        "PAR": {
            "country_id": "FR",
            "city": "Paris",
            "address_line": "12 Rue Riquet",
            "zip_code": "75019",
            "lat": 48.8885363,
            "lon": 2.3755977,
        },
        "UK": {
            "country_id": "GB",
            "city": "London",
            "address_line": "8 Viking Way",
            "zip_code": "DA8 1EW",
            "lat": 51.4915264,
            "lon": 0.1668186,
        },
        "DE": {
            "country_id": "DE",
            "city": "Frankfurt",
            # city-level coordinates from Google Maps
            "lat": 50.1109221,
            "lon": 8.6821267,
        },
        "WAW": {
            "country_id": "PL",
            "city": "Warsaw",
            "address_line": "Kazimierza Kamińskiego 6",
            "zip_code": "05-850",
            "lat": 52.2077264,
            "lon": 20.8080621,
        },
        "MIL": {
            "country_id": "IT",
            "city": "Milan",
            # OVH office in Milan, Italy
            "lat": 45.4992183,
            "lon": 9.1832528,
        },
        # North America
        "BHS": {
            "country_id": "CA",
            "city": "Beauharnois",
            "address_line": "50 Rue de l'Aluminerie",
            "state": "Quebec",
            "zip_code": "J6N 0C2",
            "lat": 45.3093037,
            "lon": -73.8965535,
        },
        "TOR": {
            "country_id": "CA",
            "city": "Toronto",
            "address_line": "17 Vondrau Dr",
            "state": "Ontario",
            "zip_code": "N3E 1B8",
            "lat": 43.4273216,
            "lon": -80.3726843,
        },
        "HIL": {
            "country_id": "US",
            "city": "Hillsboro",
            "state": "Oregon",
            # city-level coordinates from Google Maps
            "lat": 45.520137,
            "lon": -122.9898308,
        },
        "VIN": {
            "country_id": "US",
            "city": "Vint Hill",
            "address_line": "6872 Watson Ct",
            "state": "North Virginia",
            "zip_code": "20187",
            "lat": 38.7474561,
            "lon": -77.6744531,
        },
        # Asia-Pacific
        "SGP": {
            "country_id": "SG",
            "city": "Singapore",
            "address_line": "1 Paya Lebar Link",
            "zip_code": "408533",
            "lat": 1.3177101,
            "lon": 103.893902,
        },
        "SYD": {
            "country_id": "AU",
            "city": "Sydney",
            # city-level coordinates from Google Maps
            "lat": -33.8727409,
            "lon": 151.2057136,
        },
        "YNM": {
            "country_id": "IN",
            "city": "Mumbai",
            # city-level coordinates from Google Maps
            "lat": 19.0824822,
            "lon": 72.7141328,
        },
    }

    vendor.progress_tracker.start_task(name="Fetching regions", total=len(regions))
    for region in regions:
        datacenter = _get_region(region)["datacenterLocation"]
        lookup = datacenters[datacenter]
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region,
                "name": region,
                "api_reference": region,
                "display_name": f"{region} ({lookup['country_id']})",
                "aliases": [],
                "country_id": lookup["country_id"],
                "state": lookup.get("state"),
                "city": lookup.get("city"),
                "address_line": lookup.get("address_line"),
                "zip_code": lookup.get("zip_code"),
                "lon": lookup.get("lon"),
                "lat": lookup.get("lat"),
                # OVHcloud region page confirms Frankfurt (Limburg), Warsaw (Ożarów), London (Erith)
                # as specific datacenter locations opened in 2016
                "founding_year": 2016 if datacenter in ["DE", "WAW", "UK"] else None,
                "green_energy": None,
            }
        )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()

    return items


def inventory_zones(vendor) -> list[dict]:
    """List all availability zones.

    Data sources:

    - `/cloud/project/{serviceName}/region/{regionName}` API endpoint provides AZs for 3AZ regions
    - 1AZ zones have a standard "a" suffix as per <https://www.ovhcloud.com/en/about-us/global-infrastructure/expansion-regions-az/>
    """

    items = []
    regions = _get_regions()
    vendor.progress_tracker.start_task(name="Fetching zones", total=len(regions))
    for region in regions:
        zones = _get_region(region, _get_project_id())["availabilityZones"]
        if not zones:
            # single zone regions have a standard "a" suffix
            zones = [region.lower() + "-a"]
        for zone in zones:
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region,
                    "zone_id": zone,
                    "name": zone,
                    "api_reference": zone,
                    "display_name": zone,
                }
            )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return items


def inventory_servers(vendor) -> list[dict]:
    """List all server types (called "flavors" at OVHcloud)."""
    items = []

    server_plans = [
        s
        for s in _get_catalog()["addons"]
        if (
            s.get("product") == "publiccloud-instance"
            and s.get("blobs")
            and s["blobs"].get("technical")
            # TODO list Windows machines later
            and s["blobs"].get("technical").get("os", {}).get("family") == "linux"
            # filter for hourly rates for now
            and s.get("planCode", "").endswith(".consumption")
        )
    ]
    # dedupe just in case
    servers = {}
    for server_plan in server_plans:
        servers[server_plan["invoiceName"]] = server_plan

    for server_id, server in servers.items():
        blobs = server.get("blobs", {})
        if not blobs:
            continue

        commercial = blobs.get("commercial", {})
        technical = blobs.get("technical", {})
        name = commercial.get("name", server_id)
        family = _get_server_family(server_id)

        # all resources are dedicated expect for the Discovery series
        vcpus = technical.get("cpu", {}).get("cores", 0)
        cpu_allocation = (
            CpuAllocation.SHARED
            if commercial.get("brickSubtype") == "discovery"
            else CpuAllocation.DEDICATED
        )

        memory = technical.get("memory", {})
        memory_size_gb = memory.get("size", None)
        memory_size = memory_size_gb * MIB_PER_GIB if memory_size_gb else None

        _gpu_count, _gpu_memory_total, gpu_manufacturer, gpu_family, _gpu_model = (
            _get_gpu_info(server_id)
        )
        gpu = technical.get("gpu", {})
        gpu_count = _gpu_count or gpu.get("number", 0)
        gpu_memory_per_gpu = (
            gpu.get("memory").get("size", 0) * MIB_PER_GIB
            if gpu.get("memory")
            else None
        )
        gpu_memory_total = _gpu_memory_total or (
            gpu_memory_per_gpu * gpu_count if gpu_memory_per_gpu and gpu_count else None
        )
        gpu_model = _gpu_model or gpu.get("model", None)

        has_nvme = any(
            "nvme"
            in disk.get("technology", "").lower() + disk.get("interface", "").lower()
            for disk in technical.get("storage", {}).get("disks", [])
        )
        storage_type = StorageType.NVME_SSD if has_nvme else StorageType.SSD
        storage_size = sum(
            [
                disk.get("number", 1) * disk.get("capacity", 0)
                for disk in technical.get("storage", {}).get("disks", [])
            ]
        )

        status = Status.ACTIVE if "active" in blobs.get("tags", []) else Status.INACTIVE

        description_parts = [
            f"{vcpus} vCPUs",
            f"{memory_size_gb} GiB RAM",
            f"{storage_size} GB {('NVMe' if has_nvme else 'SSD')} storage",
            (
                f"{gpu_count}x{gpu_model} {int(gpu_memory_per_gpu / MIB_PER_GIB)} GiB VRAM"
                if gpu_count and gpu_model
                else None
            ),
        ]
        description = f"{family} ({', '.join(filter(None, description_parts))})"

        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "server_id": server_id,
                "name": server_id,
                "api_reference": server_id,
                "display_name": name,
                "description": description,
                "family": family,
                "vcpus": vcpus,
                # as per OVH FAQ: https://www.ovhcloud.com/en/public-cloud/virtual-instances/
                # alsoverified from lscpu on B3-8 instance (2025-11-17)
                "hypervisor": "KVM",
                "cpu_allocation": cpu_allocation,
                "cpu_cores": None,
                "cpu_speed": technical.get("cpu", {}).get("frequency"),
                "cpu_architecture": CpuArchitecture.X86_64,  # All OVHcloud instances use x86_64
                "cpu_manufacturer": None,
                "cpu_family": None,
                "cpu_model": None,
                "cpu_l1_cache": None,
                "cpu_l2_cache": None,
                "cpu_l3_cache": None,
                "cpu_flags": [],
                "cpus": [],
                "memory_amount": memory_size,
                "memory_generation": None,
                "memory_speed": None,
                "memory_ecc": None,
                "gpu_count": gpu_count,
                "gpu_memory_min": gpu_memory_per_gpu,
                "gpu_memory_total": gpu_memory_total,
                "gpu_manufacturer": gpu_manufacturer,
                "gpu_family": gpu_family,
                "gpu_model": gpu_model,
                "gpus": [],  # TODO fill this array
                "storage_size": storage_size,
                "storage_type": storage_type,
                "storages": [],
                "network_speed": technical.get("bandwidth", {}).get("level", None),
                # no bundled free traffic as all traffic is unmetered
                # https://www.ovhcloud.com/en-ie/public-cloud/prices/
                "inbound_traffic": 0,
                "outbound_traffic": 0,
                "ipv4": 1,  # each instance gets one IPv4
                "status": status,
            }
        )

    return items


def inventory_server_prices(vendor) -> list[dict]:
    """Fetch server pricing and regional availability.

    Region availability information is fetched from the
    `/cloud/project/{serviceName}/flavor` API endpoint, then the related prices
    are fetched from the `/order/catalog/public/cloud` API endpoint.
    """
    regions = scmodels_to_dict(vendor.regions, keys=["api_reference"])
    # list all addon prices and convert to a lookup dict
    catalog = _get_catalog()
    addons = {addon["planCode"]: addon for addon in catalog["addons"]}
    # list all server <> region offers with a link to the price list
    offers = _client().get(f"/cloud/project/{_get_project_id()}/flavor")
    offers = [o for o in offers if o["osType"] == "linux"]
    items = []
    vendor.progress_tracker.start_task(name="Fetching server offers", total=len(offers))
    for offer in offers:
        region = regions.get(offer["region"])
        addon = addons[offer["planCodes"]["hourly"]]
        if region is None:
            vendor.log(
                f"Excluding offer for {addon['invoiceName']} from unknown region: {offer['region']}"
            )
            continue
        # TODO check if server id is known for this vendor?
        for zone in region.zones:
            if zone.status != Status.ACTIVE:
                continue
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "zone_id": zone.zone_id,
                    "server_id": addon["invoiceName"],
                    "operating_system": addon["blobs"]["technical"]["os"]["family"],
                    "allocation": Allocation.ONDEMAND,
                    # we already filtered for hourly plan
                    "unit": PriceUnit.HOUR,
                    "price": (
                        addon["pricings"][0]["price"] / MICROCENTS_PER_CURRENCY_UNIT
                    ),
                    "price_upfront": 0,
                    "price_tiered": [],
                    "currency": catalog["locale"]["currencyCode"],
                    "status": Status.ACTIVE,
                }
            )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return items


def inventory_server_prices_spot(vendor) -> list[dict]:
    """There are no spot instances in OVHcloud Public Cloud."""
    return []


def inventory_storages(vendor) -> list[dict]:
    """List all block storage offerings.

    Data sources:

    - <https://www.ovhcloud.com/en-ie/public-cloud/block-storage/>
    - API endpoint: `/order/catalog/public/cloud` with `publiccloud-volume-classic` product name
    """
    items = [
        {
            "storage_id": "classic",
            "vendor_id": vendor.vendor_id,
            "name": "Classic Volume",
            # quote from homepage
            "description": "Perfect for the daily application needs of databases, virtual machines, and backups.",
            "storage_type": StorageType.NETWORK,
            "max_iops": 500,
            "max_throughput": 64,
            "min_size": 10,
            "max_size": 12_288,
        },
        {
            "storage_id": "high-speed",
            "vendor_id": vendor.vendor_id,
            "name": "High Speed Volume Gen 1",
            # quote from homepage
            "description": "Offers optimised and scalable performance, and is recommended for intensive workloads.",
            "storage_type": StorageType.NETWORK,
            "max_iops": 3_000,
            "max_throughput": 128,
            "min_size": 10,
            "max_size": 12_288,
        },
        {
            "storage_id": "high-speed-gen2",
            "vendor_id": vendor.vendor_id,
            "name": "High Speed Volume Gen 2",
            # quote from homepage
            "description": "Offers optimised and scalable performance, and is recommended for intensive workloads.",
            "storage_type": StorageType.NETWORK,
            "max_iops": 20_000,
            "max_throughput": 320,
            "min_size": 10,
            "max_size": 12_288,
        },
    ]
    return items


def inventory_storage_prices(vendor) -> list[dict]:
    """Extract storage prices from OVHCloud catalog.

    The catalog does not provide a detailed price list, only differentiates the
    prices of the known 3 storage types between regions with a single or three
    zones, so we assume all storage types are available in all regions.
    """
    catalog = _get_catalog()
    addons = {addon["planCode"]: addon for addon in catalog["addons"]}

    items = []
    for storage in vendor.storages:
        for region in vendor.regions:
            addon_name = f"volume.{storage.storage_id}.consumption"
            if len(region.zones) > 1:
                addon_name += ".3AZ"
            addon = addons[addon_name]
            price = addon["pricings"][0]["price"] / MICROCENTS_PER_CURRENCY_UNIT
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "storage_id": storage.storage_id,
                    "unit": PriceUnit.GB_MONTH,
                    "price": price * HOURS_PER_MONTH,
                    "currency": catalog["locale"]["currencyCode"],
                }
            )
    return items


def inventory_traffic_prices(vendor) -> list[dict]:
    """OVHcloud Public Cloud bandwidth pricing.

    As per <https://www.ovhcloud.com/en/public-cloud/prices>:

    > Outbound public network traffic is included in the price of instances on
    > all locations, except the Asia-Pacific region (Singapore, Sydney and
    > Mumbai). In the tree regions, 1 TB/month of outbound public traffic is
    > included for each Public Cloud project. Beyond this quota, each additional
    > GB of traffic is charged. Inbound network traffic from the public network
    > is included in all cases and in all regions.

    The overage traffic priced at €0.01 ex. VAT/GB (see on the homepage after
    selecting one of the Asia-Pacific regions).
    """
    # Outbound traffic pricing for Asia-Pacific regions (Singapore, Sydney, Mumbai)
    # Tier 1: 1-1024 GiB = Free (included in project quota)
    # Tier 2: 1025+ GiB = $0.0109/GB
    outbound_SYD_SGP_MUM_tiers = [
        {
            "lower": 1,
            "upper": 1024,
            "price": 0,
        },
        {
            "lower": 1025,
            "upper": "Infinity",
            "price": 0.01,
        },
    ]

    items = []
    for region in vendor.regions:
        # Incoming public traffic
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "price": 0,
                "price_tiered": [],
                "currency": "EUR",
                "unit": PriceUnit.GB_MONTH,
                "direction": TrafficDirection.IN,
            }
        )
        # Outgoing public traffic
        datacenter = _get_region(region.region_id)["datacenterLocation"]
        # Asia-Pacific region (Singapore, Sydney and Mumbai)
        is_apac = datacenter in ["SGP", "SYD", "YNM"]
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "price": 0.01 if is_apac else 0,  # max tier price
                "price_tiered": outbound_SYD_SGP_MUM_tiers if is_apac else [],
                "currency": "EUR",
                "unit": PriceUnit.GB_MONTH,
                "direction": TrafficDirection.OUT,
            }
        )
    return items


def inventory_ipv4_prices(vendor) -> list[dict]:
    """OVHcloud Public Cloud IPv4 pricing.

    Note that the API catalog endpoint states the "publiccloud-publicip-ip"
    product to be free on the single-AZ and 3AZ regions, but it's listed at 1.5
    EUR/month in the control panel for any additional public IPv4 address, so we
    use that value for now.

    Data sources:

    - <https://www.ovhcloud.com/en/public-cloud/prices>
    - OVH Control Manager
    """
    items = []
    for region in vendor.regions:
        # NOTE local zone prices are different, but these are skipped for now
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "price": 1.5,
                "currency": "EUR",
                "unit": PriceUnit.MONTH,
            }
        )
    return items
