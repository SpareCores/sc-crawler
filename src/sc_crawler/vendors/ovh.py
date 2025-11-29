from functools import cache
from os import environ, getenv
from typing import Callable

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

HOURS_PER_MONTH = 730
MICROCENTS_PER_CURRENCY_UNIT = 100_000_000
MIB_PER_GIB = 1024
# Default currency for OVHcloud prices in WE subsidiary
CURRENCY = "USD"

# Local Zone and Multi-AZ plan code suffixes (currently skipped)
LOCAL_ZONE_SUFFIXES = (".LZ", ".LZ.AF", ".LZ.EU", ".LZ.EUROZONE", ".3AZ")

# Windows instance prefix (filtered out)
WINDOWS_PREFIX = "win-"




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
def _get_project_id() -> str | None:
    """Get project ID from environment or first available project.

    Returns:
        str: Project ID from OVH_PROJECT_ID env var or first project in account
        None: If no OVH_PROJECT_ID set and no projects available
    """
    project_id = getenv("OVH_PROJECT_ID")
    if project_id:
        return project_id.strip()

    # fall back to first project in account (if any)
    try:
        projects = _client().get("/cloud/project")
        return projects[0] if projects else None
    except Exception as e:
        raise Exception(f"Failed to fetch project list from OVHcloud API: {e}") from e


@cache
def _get_regions(project_id: str = _get_project_id()) -> list[str]:
    """Fetch available regions enabled for a project.

    The catalogue-based region extraction is preferred over this function
    in general, as it's more complete: not all regions might be enabled for a projects.

    Args:
        project_id: Project ID to use for listing regions.

    Returns:
        List of region codes
    """
    try:
        return _client().get(f"/cloud/project/{project_id}/region")
    except Exception as e:
        raise Exception(f"Failed to fetch regions for project {project_id}: {e}") from e


@cache
def _get_region(region_name: str, project_id: str = _get_project_id()) -> dict:
    """Fetch region details.

    Args:
        region_name: Name of the region to fetch details for.
        project_id: Project ID to use for listing regions.

    Returns:
        Region dictionary.
    """
    return _client().get(f"/cloud/project/{project_id}/region/{region_name}")


@cache
def _get_zones(region_name: str, project_id: str = _get_project_id()) -> list[str]:
    """Fetch available zones for a region.

    Args:
        region_name: Name of the region to fetch zones for.
        project_id: Project ID to use for listing zones.

    Returns:
        List of zone codes. If there's only one zone in the region,
        return a "dummy" zone with the same name as the region in lowercase.
    """
    zones = _get_region(region_name, project_id)["availabilityZones"]
    return zones if zones else [region_name.lower()]


@cache
def _get_catalog(subsidiary: str = getenv("OVH_SUBSIDIARY", "IE")) -> dict:
    """Fetch service catalog.

    Args:
        subsidiary: OVH subsidiary to use for fetching the public catalog.

    Returns:
        Catalog dictionary with plans and addons.
    """
    try:
        return _client().get("/order/catalog/public/cloud", ovhSubsidiary=subsidiary)
    except Exception as e:
        raise Exception(f"Failed to fetch OVHcloud catalog: {e}") from e


def _get_addons_from_catalog(
    addon_family_names: list[str],
    addon_name_filter: Callable[[str], bool] | None = None,
    addon_filter: Callable[[dict], bool] | None = None,
) -> list[dict]:
    """Extract addons from catalog data for given addon family names.

    Args:
        addon_family_names: List of addon family names to extract (e.g., ["instance"], ["storage", "volume"])
        addon_name_filter: Optional function to filter addon names before matching (e.g., exclude Windows instances)
        addon_filter: Optional function to filter addons after matching by planCode (e.g., filter out addons without region configurations)

    Returns:
        List of matching addons from the catalog
    """
    catalog = _get_catalog()
    plans = catalog.get("plans", [])
    addons = catalog.get("addons", [])
    project_plan = next((p for p in plans if p.get("planCode", "") == "project"), {})

    # Collect addon names from all specified families
    addon_names = []
    for family_name in addon_family_names:
        family = next(
            (
                a
                for a in project_plan.get("addonFamilies", [])
                if a.get("name", "") == family_name
            ),
            {},
        )
        family_addon_names = family.get("addons", [])
        addon_names.extend(family_addon_names)

    # Apply optional filter to addon names
    if addon_name_filter:
        addon_names = [name for name in addon_names if addon_name_filter(name)]

    # Match addons by planCode
    matched_addons = [a for a in addons if a.get("planCode", "") in addon_names]

    # Apply optional filter to matched addons
    if addon_filter:
        matched_addons = [a for a in matched_addons if addon_filter(a)]

    return matched_addons


@cache
def _get_servers_from_catalog() -> list[dict]:
    """Extract server offerings from catalog data."""
    return _get_addons_from_catalog(
        addon_family_names=["instance"],
        addon_name_filter=lambda name: not name.startswith(WINDOWS_PREFIX),
    )


@cache
def _get_regions_from_catalog() -> list[str]:
    """Extract available regions from catalog data.

    Merges region configurations from ALL pricing variants (hourly, monthly, etc.)
    of each instance type to get the most complete regional availability list.

    Note: The 'configurations' field in the catalog represents orderable regions
    (configuration options for purchasing), not real-time availability. Some pricing
    variants (e.g., hourly) may have empty configurations while monthly variants have
    region lists. This function merges all regions from all variants to provide the
    most complete picture of where an instance type can potentially be ordered.

    Source: `/order/catalog/public/cloud` API endpoint
    """
    servers = _get_servers_from_catalog()
    regions = set()

    # iterate over all configs of all server types to list all available regions
    for server in servers:
        flavor_name = server.get("invoiceName")
        if not flavor_name:
            continue
        configurations = server.get("configurations")
        # e.g. [{'name': 'region', 'isCustom': False, 'isMandatory': False, 'values': ['BHS1', 'BHS3', 'BHS5', 'DE1', 'GRA1', 'GRA3', 'GRA5', 'SBG1', 'SBG3', 'SBG5', 'SGP1', 'SYD1', 'UK1', 'WAW1', 'GRA7']}]
        if configurations:
            for config in configurations:
                if config.get("name") == "region":
                    for region in config.get("values", []):
                        regions.add(region)

    return sorted(list(regions))


@cache
def _get_storages_from_catalog() -> list[dict]:
    """Extract storage offerings from catalog data."""

    # Filter out addons without region configurations
    def has_region_config(addon: dict) -> bool:
        configs = addon.get("configurations", [])
        return len(configs) > 0 and bool(configs[0].get("values", []))

    return _get_addons_from_catalog(
        # NOTE don't request volumes as we are only interested in block storage offerings
        addon_family_names=["storage"],
        addon_filter=has_region_config,
    )


@cache
def _get_ipv4_prices_from_catalog() -> list[dict]:
    """Extract IPv4 pricing offerings from catalog data."""
    return _get_addons_from_catalog(addon_family_names=["publicip"])


def _get_datacenter_and_city(region: str) -> tuple[str, str | None]:
    """Extract datacenter code from region identifier and map to city name."""

    # Map region codes to city names
    # Source: https://www.ovhcloud.com/en/public-cloud/regions-availability/
    datacenter_city_mapping = {
        # Europe (EMEA)
        "SBG": "Strasbourg",
        "GRA": "Gravelines",
        "RBX": "Roubaix",
        "PAR": "Paris",
        "ERI": "London",
        "LIM": "Frankfurt",
        "WAW": "Warsaw",
        "DE": "Frankfurt",
        "UK": "London",
        # North America
        "BHS": "Montreal",
        "TOR": "Toronto",
        "HIL": "Seattle",
        "VIN": "Washington DC",
        # Asia-Pacific
        "SGP": "Singapore",
        "SYD": "Sydney",
        "MUM": "Mumbai",
    }

    datacenter = _get_region(region)["datacenter"]
    return datacenter, datacenter_city_mapping.get(datacenter)


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
        tuple: (gpu_count, gpu_memory_total_gb, gpu_manufacturer, gpu_family, gpu_model)
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
            return gpu_count, gpu_count * 80, "NVIDIA", "Hopper", "H100"
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
            return gpu_count, gpu_count * 80, "NVIDIA", "Ampere", "A100"
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
            return gpu_count, gpu_count * 24, "NVIDIA", "Ampere", "A10"
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
                gpu_count * 48,
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
            return gpu_count, gpu_count * 24, "NVIDIA", "Ada Lovelace", "L4"
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
            return gpu_count, gpu_count * 32, "NVIDIA", "Volta", "V100S"
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
            return gpu_count, gpu_count * 16, "NVIDIA", "Volta", "V100"
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
                gpu_count * 16,
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
    Verified on ovhcloud.com:
    - ISO/IEC 27001/27017/27018 (page: /en/compliance/iso-27001-27017-27018/)
    - SOC 1, SOC 2, SOC 3 with SOC 2 Type 2 details (page: /en/compliance/soc-1-2-3/)
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

    Further information: https://www.ovhcloud.com/en/public-cloud/regions-availability/
    """
    items = []
    regions = _get_regions()

    # TODO create a joint mapping of countries/zip etc for easier maintenance?

    # Map OVHcloud region codes to country codes
    # Source: https://www.ovhcloud.com/en/public-cloud/regions-availability/
    region_country_mapping = {
        # Europe (EMEA)
        "SBG": "FR",  # Strasbourg, France
        "GRA": "FR",  # Gravelines, France
        "RBX": "FR",  # Roubaix, France
        "PAR": "FR",  # Paris, France (3-AZ)
        "ERI": "GB",  # London (Erith), United Kingdom
        "LIM": "DE",  # Frankfurt (Limburg), Germany
        "WAW": "PL",  # Warsaw, Poland
        "DE": "DE",  # Frankfurt, Germany
        "UK": "GB",  # London, United Kingdom
        # North America
        "BHS": "CA",  # Beauharnois (Montreal), Quebec, Canada
        "TOR": "CA",  # Toronto, Canada
        "HIL": "US",  # Hillsboro (Seattle/Portland), Oregon, USA
        "VIN": "US",  # Vint Hill (Washington DC), Virginia, USA
        # Asia-Pacific
        "SGP": "SG",  # Singapore
        "SYD": "AU",  # Sydney, Australia
        "MUM": "IN",  # Mumbai, India
    }
    # NOTE this could be fetched via the following API endpoint as well:
    # _get_region("UK")["countryCode"]

    # Coordinates for OVHcloud datacenter locations
    # Source: Mixed - Exact datacenter addresses from Google Maps search (retrieved 2025-11-17)
    #         and city-level coordinates from Google Maps Geocoding API
    region_coordinates = {
        # Strasbourg - 9 Rue du Bass. de l'Industrie, 67000
        "SBG": (48.5854388, 7.7974307),
        # Gravelines - 1 Rte de la Frm Masson, 59820 Gravelines
        "GRA": (51.0166852, 2.1551437),
        # Roubaix - 2 Rue Kellermann, 59100 (HQ)
        "RBX": (50.691834, 3.2003148),
        # Paris - 12 Rue Riquet, 75019
        "PAR": (48.8885363, 2.3755977),
        # London (Erith) - 8 Viking Way, Erith DA8 1EW, UK
        "ERI": (51.4915264, 0.1668186),
        # Warsaw (Ożarów) - Kazimierza Kamińskiego 6, 05-850 Ożarów Mazowiecki
        "WAW": (52.2077264, 20.8080621),
        # Beauharnois - 50 Rue de l'Aluminerie, QC J6N 0C2
        "BHS": (45.3093037, -73.8965535),
        # Singapore - 1 Paya Lebar Link, PLQ 1, #11-02, 408533
        "SGP": (1.3177101, 103.893902),
        # Toronto (Cambridge) - 17 Vondrau Dr, Cambridge, ON N3E 1B8
        "TOR": (43.4273216, -80.3726843),
        # Vint Hill (Warrenton) - 6872 Watson Ct, Warrenton, VA 20187, USA
        "VIN": (38.7474561, -77.6744531),
        # Frankfurt (Limburg), Germany (city-level)
        "LIM": (50.1109221, 8.6821267),
        # London, United Kingdom (using Erith coordinates as proxy)
        "UK": (51.4915264, 0.1668186),
        # Frankfurt, Germany (city-level)
        "DE": (50.1109221, 8.6821267),
        # Hillsboro, Oregon, USA (city-level)
        "HIL": (45.520137, -122.9898308),
        # Sydney, Australia (city-level)
        "SYD": (-33.8727409, 151.2057136),
        # Mumbai, India (city-level)
        "MUM": (19.0824822, 72.7141328),
    }

    # Exact addresses for datacenters where known
    # Source: Google Maps search (retrieved 2025-11-17)
    # Format: street + city (and state/province where relevant); zip/postal codes are stored separately in region_zip_codes
    region_addresses = {
        "SBG": "9 Rue du Bass. de l'Industrie, Strasbourg",
        "GRA": "1 Rte de la Frm Masson, Gravelines",
        "RBX": "2 Rue Kellermann, Roubaix",
        "PAR": "12 Rue Riquet, Paris",
        "BHS": "50 Rue de l'Aluminerie, Beauharnois, QC",
        "WAW": "Kazimierza Kamińskiego 6, Ożarów Mazowiecki",
        "SGP": "1 Paya Lebar Link, PLQ 1, Paya Lebar Quarter, #11-02, Singapore",
        "TOR": "17 Vondrau Dr, Cambridge, ON",
        "ERI": "8 Viking Way, Erith",
        "VIN": "6872 Watson Ct, Warrenton, VA",
    }

    # Zip/postal codes for datacenters where known
    region_zip_codes = {
        "SBG": "67000",
        "GRA": "59820",
        "RBX": "59100",
        "PAR": "75019",
        "BHS": "J6N 0C2",
        "WAW": "05-850",
        "SGP": "408533",
        "TOR": "N3E 1B8",
        "ERI": "DA8 1EW",
        "VIN": "20187",
    }

    # State/province mapping
    region_state_mapping = {
        "BHS": "Quebec",
        "TOR": "Ontario",
        "VIN": "Virginia",
        "HIL": "Oregon",
    }

    for region_code in regions:
        datacenter, city = _get_datacenter_and_city(region_code)
        country_id = region_country_mapping.get(datacenter)
        state = region_state_mapping.get(datacenter)
        coords = region_coordinates.get(datacenter)
        lon = coords[1] if coords else None
        lat = coords[0] if coords else None
        address = region_addresses.get(datacenter)
        zip_code = region_zip_codes.get(datacenter)

        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region_code,
                "name": region_code,
                "api_reference": region_code,
                "display_name": f"{city} ({region_code})" if city else region_code,
                "aliases": [],
                "country_id": country_id,
                "state": state,
                "city": city,
                "address_line": address,
                "zip_code": zip_code,
                "lon": lon,
                "lat": lat,
                # OVHcloud region page confirms Frankfurt (Limburg), Warsaw (Ożarów), London (Erith)
                # as specific datacenter locations opened in 2016
                "founding_year": 2016 if region_code in ["LIM", "WAW", "UK"] else None,
                "green_energy": None,
            }
        )

    return items


def inventory_zones(vendor) -> list[dict]:
    """List all availability zones.

    Most regions are single-zone without a named availability zone, for which we
    create a dummy zone with the same name as the region in lowercase. Multi-AZ
    regions (like Paris with 3-AZ) have named availability zones made available
    via the project API.
    """

    items = []
    regions = _get_regions()
    for region in regions:
        zones = _get_zones(region)
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
    return items


def inventory_servers(vendor) -> list[dict]:
    """List all server types (called "flavors" at OVHcloud)."""
    items = []
    servers = _get_servers_from_catalog()

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

        blobs = server.get("blobs", {})
        if not blobs:
            continue  # Skip if no blob data available
        commercial = blobs.get("commercial", {})
        technical = blobs.get("technical", {})
        brick_subtype = commercial.get("brickSubtype", "")
        name = commercial.get("name", server_id)
        display_name = brick_subtype if brick_subtype else name
        server_family = _get_server_family(server_id)
        cpu = technical.get("cpu", {})
        gpu = technical.get("gpu", {})
        bandwidth = technical.get("bandwidth", {})
        bandwidth_level = bandwidth.get("level", None)
        # all resources are dedicated expect for the Discovery series
        cpu_allocation = (
            CpuAllocation.SHARED
            if commercial.get("brickSubtype") == "discovery"
            else CpuAllocation.DEDICATED
        )
        memory = technical.get("memory", {})
        memory_size_gb = memory.get("size", None)
        memory_size = memory_size_gb * MIB_PER_GIB if memory_size_gb else None
        )
        gpu_count = gpu.get("number", 0)
        gpu_memory_per_gpu = (
            gpu.get("memory").get("size", 0) if gpu.get("memory") else None
        )
        gpu_memory_total_gb = (
            gpu_memory_per_gpu * gpu_count if gpu_memory_per_gpu and gpu_count else None
        )
        gpu_model = (
            f"{gpu.get('model')} {gpu.get('memory').get('interface')}" if gpu else None
        )
        _gpu_count, _gpu_memory_total_gb, gpu_manufacturer, gpu_family, _gpu_model = (
            _get_gpu_info(server_id)
        )
        if not gpu_count and _gpu_count:
            gpu_count = _gpu_count
        if not gpu_memory_total_gb and _gpu_memory_total_gb:
            gpu_memory_total_gb = _gpu_memory_total_gb
        if not gpu_model and _gpu_model:
            gpu_model = _gpu_model
        gpu_memory_total = (
            gpu_memory_total_gb * MIB_PER_GIB if gpu_memory_total_gb else None
        )
        has_nvme = any(
            "nvme"
            in [disk.get("technology", "").lower(), disk.get("interface", "").lower()]
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

        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "server_id": server_id,
                "name": server_id,
                "api_reference": server_id,
                "display_name": display_name,
                "description": None,  # TODO: add capabilities info?
                "family": server_family,
                "vcpus": vcpus,
                # Verified from lscpu on B3-8 instance (2025-11-17)
                "hypervisor": "KVM" if cpu_allocation == CpuAllocation.SHARED else None,
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

    Region availability information varies across pricing types. Some pricing variants
    (e.g., hourly) may have empty configurations while others (e.g., monthly) contain region lists.
    We merge regions from ALL pricing variants of each flavor to get complete availability,
    then apply those merged regions to hourly pricing entries only.

    The 'configurations' field represents orderable regions (configuration options for purchasing),
    not real-time availability, but it's the best available data from the catalog.

    Source: /order/catalog/public/cloud API endpoint
    """
    items = []
    server_region: dict[str, set[str]] = {}
    servers = _get_servers_from_catalog()
    client = _client()
    flavors = _get_flavors(client)

    # First pass: collect and merge regions from ALL pricing variants of each flavor
    for server in servers:
        server_id = server.get("invoiceName", "")
        if not server_id:
            continue

        configurations = server.get("configurations", [])
        if configurations:
            for config in configurations:
                if config.get("name") == "region":
                    regions = config.get("values", [])
                    if regions:
                        if server_id not in server_region:
                            server_region[server_id] = set()
                        server_region[server_id].update(regions)
    # Second pass: create pricing entries using collected/merged regions
    # Note: Only process hourly consumption plans (.consumption) because the database schema
    # does not support multiple price units (unit is not part of primary key). Monthly plans
    # would overwrite hourly plans if both are inserted.
    # TODO: add support for monthly plans later if needed.
    for server in servers:
        plancode = server.get("planCode", "")
        server_id = server.get("invoiceName", "")
        if not server_id:
            continue

        # Skip monthly plans - only process hourly consumption plans
        if "monthly" in plancode.lower():
            continue

        blobs = server.get("blobs", {})
        if not blobs:
            continue  # Skip if no blob data available

        # Skip Local Zone and Multi-AZ variants
        # TODO: add support later
        if any(plancode.endswith(suffix) for suffix in LOCAL_ZONE_SUFFIXES):
            continue

        price = (
            server.get("pricings", [])[0].get("price", None)
            if server.get("pricings")
            else None
        )
        interval_unit_str = (
            server.get("pricings", [])[0].get("intervalUnit", "")
            if server.get("pricings")
            else ""
        )
        interval_unit = (
            PriceUnit.HOUR if interval_unit_str == "hour" else PriceUnit.MONTH
        )
        status = Status.ACTIVE if "active" in blobs.get("tags", []) else Status.INACTIVE
        technical = blobs.get("technical", {})
        os = technical.get("os", {}).get("family", "linux")

        if price:
            price = price / MICROCENTS_PER_CURRENCY_UNIT

        # Use merged regions from all variants of this flavor
        regions = list(server_region.get(server_id, set()))

        # If no regions found at all for this flavor in catalog, try to get from flavors API
        # Note: This fallback requires project_id, which may not always be available
        if not regions:
            regions = [
                f.get("region")
                for f in flavors
                if f.get("planCodes", {}).get("hourly") == plancode and f.get("region")
            ]
            if not regions:
                continue

        for region in regions:
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region,
                    "zone_id": region,
                    "server_id": server_id,
                    "operating_system": os,
                    "allocation": Allocation.ONDEMAND,
                    "unit": interval_unit,
                    "price": price,
                    "price_upfront": 0,
                    "price_tiered": [],
                    "currency": CURRENCY,
                    "status": status,
                }
            )
    return items


def inventory_server_prices_spot(vendor) -> list[dict]:
    """There are no spot instances in OVHcloud Public Cloud."""
    return []


def inventory_storages(vendor) -> list[dict]:
    """Inventory OVHCloud storage types dynamically from catalog."""
    items = []
    items_dict = {}
    storages = _get_storages_from_catalog()

    for storage in storages:
        if storage.get("invoiceName", "") not in items_dict:
            items_dict[storage.get("invoiceName", "")] = storage

    for storage_id, storage in items_dict.items():
        blobs = storage.get("blobs", {})
        commercial = blobs.get("commercial", {})
        technical = blobs.get("technical", {})

        # Determine storage type based on brick and name
        brick = commercial.get("brick", "")
        brick_subtype = commercial.get("brickSubtype", "")
        name = commercial.get("name", storage_id)

        # Initialize specs
        max_iops = None
        max_size = None

        # Extract volume specifications
        if brick == "volume":
            volume_specs = technical.get("volume", {})

            # Capacity limits (in GiB)
            capacity = volume_specs.get("capacity", {})
            max_size = capacity.get("max")

            # IOPS specifications
            iops_specs = volume_specs.get("iops", {})
            if iops_specs:
                max_iops = iops_specs.get("level")
                # 'guaranteed' field indicates if IOPS is guaranteed (True) or best-effort (False)

        # Display name from brick subtype or name
        display_name = brick_subtype if brick_subtype else name

        items.append(
            {
                "storage_id": storage_id.replace(
                    " ", "_"
                ),  # fix "bandwidth_storage in" invoiceName
                "vendor_id": vendor.vendor_id,
                "name": display_name,
                "description": None,
                "storage_type": StorageType.NETWORK,
                "max_iops": max_iops,
                "max_throughput": None,
                "min_size": None,
                "max_size": max_size,
            }
        )

    return items


def inventory_storage_prices(vendor) -> list[dict]:
    """Extract storage prices from OVHCloud catalog.

    Note: Region availability information varies across pricing types. Some pricing variants
    (e.g., hourly) may have empty configurations while others (e.g., monthly) contain region lists.
    We merge regions from ALL pricing variants of each storage type to get complete availability.

    Source: /order/catalog/public/cloud API endpoint
    """
    items = []
    storages = _get_storages_from_catalog()

    # First pass: collect and merge regions from all pricing variants of each storage type
    storage_regions: dict[str, set[str]] = {}
    for storage in storages:
        storage_id = storage.get("invoiceName", "")
        if not storage_id:
            continue

        configurations = storage.get("configurations", [])
        if configurations:
            for config in configurations:
                if config.get("name") == "region":
                    regions = config.get("values", [])
                    if regions:
                        if storage_id not in storage_regions:
                            storage_regions[storage_id] = set()
                        storage_regions[storage_id].update(regions)

    # Second pass: create pricing entries using merged regions
    for storage in storages:
        plancode = storage.get("planCode", "")
        storage_id = storage.get("invoiceName", "")
        if not storage_id:
            continue

        # Skip Local Zone and Multi-AZ variants
        # TODO: add support later
        if any(plancode.endswith(suffix) for suffix in LOCAL_ZONE_SUFFIXES):
            continue

        price = (
            storage.get("pricings", [])[0].get("price", None)
            if storage.get("pricings")
            else None
        )
        if price:
            description = (
                storage.get("pricings", [])[0].get("description", "")
                if storage.get("pricings")
                else ""
            )
            is_hourly = "hourly" in description
            price = price * HOURS_PER_MONTH if is_hourly else price
            price = price / MICROCENTS_PER_CURRENCY_UNIT

        # Use merged regions from all variants of this storage type
        regions = list(storage_regions.get(storage_id, set()))

        # If no regions found at all for this storage type, skip it
        if not regions:
            continue

        for region in regions:
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region,
                    # fix "bandwidth_storage in" invoiceName
                    "storage_id": storage_id.replace(" ", "_"),
                    "unit": PriceUnit.GB_MONTH,
                    "price": price,
                    "currency": CURRENCY,
                }
            )

    return items


def inventory_traffic_prices(vendor) -> list[dict]:
    """OVHcloud Public Cloud bandwidth pricing.
    "Outbound public network traffic is included in the price of instances on all locations,
    except the Asia-Pacific region (Singapore, Sydney and Mumbai). In the tree regions,
    1 TB/month of outbound public traffic is included for each Public Cloud project.
    Beyond this quota, each additional GB of traffic is charged.
    Inbound network traffic from the public network is included in all cases and in all regions."
    Source: https://www.ovhcloud.com/en/public-cloud/prices
    For outbound traffic in SYD, SGP, MUM regions, the pricing tiers are copied from the OVHcloud catalog.
    """
    # Outbound traffic pricing for Asia-Pacific regions (Singapore, Sydney, Mumbai)
    # Tier 1: 1-1024 GiB = Free (included in project quota)
    # Tier 2: 1025+ GiB = $0.0109/GB
    outbound_SYD_SGP_MUM_tiers = [
        {
            "lower": 1,
            "upper": 1024,
            "price": 0,  # Included in quota
        },
        {
            "lower": 1025,
            "upper": "Infinity",
            "price": 0.0109,  # Converted from 1090000 microcents
        },
    ]

    items = []
    for region in vendor.regions:
        # Inbound traffic (free everywhere)
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "price": 0,
                "price_tiered": [],
                "currency": CURRENCY,
                "unit": PriceUnit.GB_MONTH,
                "direction": TrafficDirection.IN,
            }
        )
        # Outbound traffic
        is_apac = region.region_id.startswith(("SGP", "SYD", "MUM"))
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "price": 0.0109 if is_apac else 0,  # Set to max tier price
                "price_tiered": outbound_SYD_SGP_MUM_tiers if is_apac else [],
                "currency": CURRENCY,
                "unit": PriceUnit.GB_MONTH,
                "direction": TrafficDirection.OUT,
            }
        )
    return items


def inventory_ipv4_prices(vendor) -> list[dict]:
    """OVHcloud Public Cloud IPv4 pricing.

    Source: https://www.ovhcloud.com/en/public-cloud/prices (retrieved 2025-11-23)

    IPv4 Pricing Model:
    - Regular Compute Instances (B2/B3, C2/C3, R2/R3, D2, I1, BM-*): IPv4 included by default (FREE)
    - Local Zone Instances: IPv4 NOT included, pricing only shown in Control Panel during order
    - Floating IP: $0.0027/hour ($~2/month) per IPv4 (/32) address

    Currently returning 0 as IPv4 is included by default for standard regions.
    """
    items = []
    for region in vendor.regions:
        # TODO: .LZ, .LZ.EU, .LZ.AF variants are not free, but these are skipped for now
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "price": 0,
                "currency": CURRENCY,
                "unit": PriceUnit.MONTH,
            }
        )
    return items
