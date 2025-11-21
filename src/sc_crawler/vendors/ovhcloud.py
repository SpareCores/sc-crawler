import os
from functools import cache
import ovh
from ..lookup import map_compliance_frameworks_to_vendor
from ..table_fields import CpuAllocation, CpuArchitecture, Status, StorageType, Allocation, PriceUnit
from ..utils import scmodels_to_dict

HOURS_PER_MONTH = 730
MICROCENTS_PER_CURRENCY_UNIT = 100_000_000
MIB_PER_GIB = 1024


@cache
def _client() -> ovh.Client:
    """Create OVHcloud API client using the classic authentication method.

    It uses OVHcloud's classic API authentication with application key/secret and consumer key.

    Environment Variables Required:
        OVH_ENDPOINT: API endpoint (ovh-eu, ovh-ca, ovh-us, etc.)
        OVH_APP_KEY: Application key from createApp (https://eu.api.ovh.com/createApp/ in EU for example)
        OVH_APP_SECRET: Application secret from createApp
        OVH_CONSUMER_KEY: Consumer key (auto-generated on first run if missing)
    """
    try:
        endpoint = os.getenv('OVH_ENDPOINT').strip()
    except (KeyError, AttributeError):
        raise KeyError("Missing environment variable: OVH_ENDPOINT")
    if endpoint not in ovh.client.ENDPOINTS.keys():
        raise KeyError(f"Invalid OVH_ENDPOINT. Must be one of: {', '.join(ovh.client.ENDPOINTS.keys())}")
    try:
        application_key = os.getenv('OVH_APP_KEY').strip()
    except (KeyError, AttributeError):
        raise KeyError("Missing environment variable: OVH_APP_KEY")
    try:
        application_secret = os.getenv('OVH_APP_SECRET').strip()
    except (KeyError, AttributeError):
        raise KeyError("Missing environment variable: OVH_APP_SECRET")

    # Check if consumer key exists
    consumer_key = os.getenv('OVH_CONSUMER_KEY')

    if not consumer_key or not consumer_key.strip():
        # Consumer key not set - generate it interactively
        print("OVH_CONSUMER_KEY not found. Generating a new consumer key...")

        # Create client WITHOUT consumer key to request one
        temp_client = ovh.Client(
            endpoint=endpoint,
            application_key=application_key,
            application_secret=application_secret,
        )

        # Request consumer key with required permissions
        ck = temp_client.new_consumer_key_request()
        ck.add_recursive_rules(ovh.API_READ_ONLY, '/')

        # Request token
        validation = ck.request()

        print("\n" + "=" * 70)
        print("IMPORTANT: Please visit the following URL to authenticate:")
        print(validation['validationUrl'])
        print("=" * 70)
        print("\nAfter authentication, set this environment variable:")
        print(f"export OVH_CONSUMER_KEY='{validation['consumerKey']}'")
        print("=" * 70 + "\n")

        input("Press Enter after you have completed authentication...")

        consumer_key = validation['consumerKey']
    else:
        consumer_key = consumer_key.strip()

    return ovh.Client(
        endpoint=endpoint,
        application_key=application_key,
        application_secret=application_secret,
        consumer_key=consumer_key,
    )


@cache
def _get_project_id(client) -> str | None:
    """Get project ID from environment or first available project.

    Returns:
        str: Project ID from OVH_PROJECT_ID env var or first project in account
        None: If no OVH_PROJECT_ID set and no projects available
    """
    project_id = os.getenv('OVH_PROJECT_ID')
    if project_id:
        return project_id.strip()

    # No env var set, fetch from API
    projects = client.get('/cloud/project')
    return projects[0] if projects else None


@cache
def _get_regions(client, project_id=None) -> list[str]:
    """Fetch available regions."""
    if not project_id:
        project_id = _get_project_id(client)
    return client.get(f'/cloud/project/{project_id}/region')


@cache
def _get_flavors(client, project_id=None) -> list[dict]:
    """Fetch available flavors for a project."""
    if not project_id:
        project_id = _get_project_id(client)
    # Fetch all available flavors for the project
    flavors = client.get(f'/cloud/project/{project_id}/flavor')
    # Filter out Windows servers
    return [f for f in flavors if f.get('osType') != 'windows']


@cache
def _get_catalog(client) -> dict:
    """Fetch service catalog.
    Using OVH Subsidiary "WE" (Western Europe) for consistent catalog data."""
    return client.get("/order/catalog/public/cloud?ovhSubsidiary=WE")


@cache
def _get_servers_from_catalog() -> list[dict]:
    """Extract server offerings from catalog data."""
    client = _client()
    catalog = _get_catalog(client)

    plans = catalog.get('plans', [])
    addons = catalog.get('addons', [])
    project_plan = next((p for p in plans if p.get('planCode', '') == 'project'), {})
    server_addon_names = next((a for a in project_plan.get('addonFamilies', []) if a.get('name', '') == 'instance'),
                              {}).get('addons', [])
    server_addon_names = [a for a in server_addon_names if not a.startswith('win')]  # Exclude Windows instances
    server_addons = [a for a in addons if a.get('planCode', '') in server_addon_names]
    return server_addons


@cache
def _get_regions_from_catalog() -> list[str]:
    """Extract available regions from catalog data."""
    servers = _get_servers_from_catalog()
    regions = set()
    for server in servers:
        configurations = server.get("configurations", [])
        if configurations and len(configurations) > 0:
            server_regions = configurations[0].get("values", [])
            if server_regions:
                for region in server_regions:
                    regions.add(region)
    return list(regions)


@cache
def _get_storages_from_catalog() -> list[dict]:
    """Extract storage offerings from catalog data."""
    client = _client()
    catalog = _get_catalog(client)

    plans = catalog.get('plans', [])
    addons = catalog.get('addons', [])
    project_plan = next((p for p in plans if p.get('planCode', '') == 'project'), {})
    storage_addon_names = next((a for a in project_plan.get('addonFamilies', []) if a.get('name', '') == 'storage'),
                               {}).get(
        'addons', [])
    # Filter out addons without region configurations
    storage_addons = [a for a in addons if
                      a.get('planCode', '') in storage_addon_names and
                      len(a.get("configurations", [])) > 0 and
                      a.get("configurations", [])[0].get("values", [])]
    volume_addon_names = next((a for a in project_plan.get('addonFamilies', []) if a.get('name', '') == 'volume'),
                              {}).get(
        'addons', [])
    # Filter out addons without region configurations
    volume_addons = [a for a in addons if
                     a.get('planCode', '') in volume_addon_names and
                     len(a.get("configurations", [])) > 0 and
                     a.get("configurations", [])[0].get("values", [])]
    return storage_addons + volume_addons


def _get_base_region_and_city(region):
    """Extract base region code from various formats and map to city name."""

    # Map region codes to city names
    # Source: https://www.ovhcloud.com/en/public-cloud/regions-availability/
    region_city_mapping = {
        # Europe (EMEA)
        'SBG': 'Strasbourg',
        'GRA': 'Gravelines',
        'RBX': 'Roubaix',
        'PAR': 'Paris',
        'ERI': 'London',
        'LIM': 'Frankfurt',
        'WAW': 'Warsaw',
        'DE': 'Frankfurt',
        'UK': 'London',
        # North America
        'BHS': 'Montreal',
        'TOR': 'Toronto',
        'HIL': 'Seattle',
        'VIN': 'Washington DC',
        # Asia-Pacific
        'SGP': 'Singapore',
        'SYD': 'Sydney',
        'MUM': 'Mumbai',
    }

    # Extract base region code from various formats:
    # - Simple: 'GRA', 'BHS', 'DE' -> 'GRA', 'BHS', 'DE'
    # - With number: 'GRA9', 'BHS5', 'DE1' -> 'GRA', 'BHS', 'DE'
    # - Descriptive: 'CA-EAST-TOR', 'EU-WEST-PAR' -> 'TOR', 'PAR'
    # - Special: 'RBX-A', 'RBX-ARCHIVE' -> 'RBX', 'RBX'
    if '-' in region:
        parts = region.split('-')
        # Try first part (for RBX-ARCHIVE, RBX-A)
        first_part = ''.join([c for c in parts[0] if not c.isdigit()])
        # Try last part (for CA-EAST-TOR, EU-WEST-PAR)
        last_part = ''.join([c for c in parts[-1] if not c.isdigit()])

        # Prefer the part that exists in our mappings
        if last_part in region_city_mapping:
            base_region = last_part
        else:
            base_region = first_part
    else:
        # Handle simple format with or without numbers (e.g., 'GRA11' -> 'GRA')
        base_region = ''.join([c for c in region if not c.isdigit()])

    return base_region, region_city_mapping.get(base_region)


def _get_server_family(flavor_name):
    """Map OVHcloud flavor name to server family.

    Server families are displayed on the pricing page:
    https://www.ovhcloud.com/en/public-cloud/prices/ (retrieved 2025-11-19)

    Returns:
        str: Server family name (e.g., 'General Purpose', 'Compute Optimized')
    """
    name_lower = flavor_name.lower()

    # Extract prefix (e.g., 'b2-7' -> 'b2', 't1-45' -> 't1')
    prefix = name_lower.split('-')[0]

    # GPU instances
    if prefix in ['t1', 't2', 'a10', 'a100', 'l4', 'l40s', 'h100', 'rtx5000']:
        return 'Cloud GPU'

    # Metal instances
    if prefix == 'bm':
        return 'Metal'

    # General Purpose: b2, b3 families
    if prefix in ['b2', 'b3']:
        return 'General Purpose'

    # Compute Optimized: c2, c3 families
    if prefix in ['c2', 'c3']:
        return 'Compute Optimized'

    # Memory Optimized: r2, r3 families
    if prefix in ['r2', 'r3']:
        return 'Memory Optimized'

    # Discovery: d2 family
    if prefix == 'd2':
        return 'Discovery'

    # Storage Optimized: i1 family
    if prefix == 'i1':
        return 'Storage Optimized'

    # Default fallback
    return None


def _get_cpu_info(flavor_name):
    """Map flavor name to CPU manufacturer and model based on OVHcloud documentation.

    Sources:
    - OVHcloud Cloud Manager: Direct verification (retrieved 2025-11-19)
    - lscpu verification on B3-8 instance (2025-11-17)
    """
    name_lower = flavor_name.lower()

    # CPU model verified from lscpu on B3-8 instance (2025-11-17): AMD EPYC-Milan Processor (Family 25, Model 1)
    if name_lower.startswith('b3-'):
        return 'AMD', 'EPYC Milan', 2.3
    if name_lower.startswith('c3-'):
        return None, None, 2.3
    if name_lower.startswith('r3-'):
        return None, None, 2.3

    # 2nd generation instances (b2, c2, r2)
    # - B2 series: 2.0 GHz (balanced)
    # - C2 series: 3.0 GHz (compute-optimized)
    # - R2 series: 2.2 GHz (RAM-optimized)
    if name_lower.startswith('c2-'):
        return None, None, 3.0
    if name_lower.startswith('r2-'):
        return None, None, 2.2
    if name_lower.startswith('b2-'):
        return None, None, 2.0

    # Discovery instances (d2) - 2.0 GHz
    if name_lower.startswith('d2-'):
        return None, None, 2.0

    # Storage optimized instances (i1) - 2.2 GHz
    if name_lower.startswith('i1-'):
        return None, None, 2.2

    # Bare Metal instances
    # - bm-s1 (Small): 4 cores @ 4.0 GHz
    # - bm-m1 (Medium): 8 cores @ 3.7 GHz
    # - bm-l1 (Large): 16 cores @ 3.1 GHz
    if name_lower == 'bm-s1':
        return None, None, 4.0
    if name_lower == 'bm-m1':
        return None, None, 3.7
    if name_lower == 'bm-l1':
        return None, None, 3.1
    if name_lower.startswith('bm-'):
        return None, None, None  # Unknown BM type

    # H100 series - 3.0 GHz
    if name_lower.startswith('h100-'):
        return None, None, 3.0

    # A100 series - No CPU info available
    if name_lower.startswith('a100-'):
        return None, None, None

    # A10 series - 3.3 GHz
    if name_lower.startswith('a10-'):
        return None, None, 3.3

    # L40S series - 2.75 GHz
    if name_lower.startswith('l40s-'):
        return None, None, 2.75

    # L4 series - 2.75 GHz
    if name_lower.startswith('l4-'):
        return None, None, 2.75

    # Tesla V100S (t2) series - 2.9 GHz
    if name_lower.startswith('t2-') or name_lower.startswith('t2-le-'):
        return None, None, 2.9

    # Tesla V100 (t1) series - 3.0 GHz
    if name_lower.startswith('t1-') or name_lower.startswith('t1-le-'):
        return None, None, 3.0

    # Quadro RTX 5000 series - 3.3 GHz
    if name_lower.startswith('rtx5000-'):
        return None, None, 3.3

    # Default: unknown
    return None, None, None


def _get_gpu_info(flavor_name):
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
    if name_lower.startswith('h100-'):
        try:
            size = int(name_lower.split('-')[1])
            gpu_count = size // 380
            return gpu_count, gpu_count * 80, 'NVIDIA', 'Hopper', 'H100 80GB HBM3'
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA A100 (80GB HBM2e per GPU) - Ampere Architecture
    # - a100-180: 1x A100, 180 GB RAM, 15 vCores, 300 GB NVMe, 8,000 Mbit/s
    # - a100-360: 2x A100, 360 GB RAM, 30 vCores, 500 GB NVMe, 16,000 Mbit/s
    # - a100-720: 4x A100, 720 GB RAM, 60 vCores, 500 GB NVMe, 25,000 Mbit/s
    if name_lower.startswith('a100-'):
        try:
            size = int(name_lower.split('-')[1])
            gpu_count = size // 180
            return gpu_count, gpu_count * 80, 'NVIDIA', 'Ampere', 'A100 80GB HBM2e'
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA A10 Tensor Core GPU (24GB GDDR6 per GPU) - Ampere Architecture
    # OVHcloud instances:
    # - a10-45: 1x A10, 45 GB RAM, 30 vCores (3.3 GHz), 400 GB SSD, 8,000 Mbit/s
    # - a10-90: 2x A10, 90 GB RAM, 60 vCores (3.3 GHz), 400 GB SSD, 16,000 Mbit/s
    # - a10-180: 4x A10, 180 GB RAM, 120 vCores (3.3 GHz), 400 GB SSD, 25,000 Mbit/s
    if name_lower.startswith('a10-'):
        try:
            size = int(name_lower.split('-')[1])
            gpu_count = size // 45
            return gpu_count, gpu_count * 24, 'NVIDIA', 'Ampere', 'A10 24GB GDDR6'
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA L40S (48GB GDDR6 per GPU) - Ada Lovelace Architecture
    # OVHcloud instances:
    # - l40s-90: 1x L40S, 90 GB RAM, 15 vCores (2.75 GHz), 400 GB NVMe, 8,000 Mbit/s
    # - l40s-180: 2x L40S, 180 GB RAM, 30 vCores (2.75 GHz), 400 GB NVMe, 16,000 Mbit/s
    # - l40s-360: 4x L40S, 360 GB RAM, 60 vCores (2.75 GHz), 400 GB NVMe, 25,000 Mbit/s
    if name_lower.startswith('l40s-'):
        try:
            size = int(name_lower.split('-')[1])
            gpu_count = size // 90
            return gpu_count, gpu_count * 48, 'NVIDIA', 'Ada Lovelace', 'L40S 48GB GDDR6'
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA L4 Tensor Core GPU (24GB GDDR6 per GPU) - Ada Lovelace Architecture
    # OVHcloud instances:
    # - l4-90: 1x L4, 90 GB RAM, 22 vCores (2.75 GHz), 400 GB NVMe, 8,000 Mbit/s
    # - l4-180: 2x L4, 180 GB RAM, 45 vCores (2.75 GHz), 400 GB NVMe, 16,000 Mbit/s
    # - l4-360: 4x L4, 360 GB RAM, 90 vCores (2.75 GHz), 400 GB NVMe, 25,000 Mbit/s
    if name_lower.startswith('l4-'):
        try:
            size = int(name_lower.split('-')[1])
            gpu_count = size // 90
            return gpu_count, gpu_count * 24, 'NVIDIA', 'Ada Lovelace', 'L4 24GB GDDR6'
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
    if name_lower.startswith('t2-') or name_lower.startswith('t2-le-'):
        try:
            # Extract size: 't2-45' -> 45, 't2-le-45' -> 45
            parts = name_lower.split('-')
            size = int(parts[-1])
            gpu_count = size // 45
            return gpu_count, gpu_count * 32, 'NVIDIA', 'Volta', 'Tesla V100S 32GB HBM2'
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
    if name_lower.startswith('t1-') or name_lower.startswith('t1-le-'):
        try:
            # Extract size: 't1-45' -> 45, 't1-le-45' -> 45
            parts = name_lower.split('-')
            size = int(parts[-1])
            gpu_count = size // 45
            return gpu_count, gpu_count * 16, 'NVIDIA', 'Volta', 'Tesla V100 16GB HBM2'
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # NVIDIA Quadro RTX 5000 (16GB GDDR6 per GPU) - Turing Architecture
    # OVHcloud instances:
    # - rtx5000-28: 1x Quadro RTX 5000, 28 GB RAM, 4 vCores (3.3 GHz), 400 GB SSD, 2,000 Mbit/s
    # - rtx5000-56: 2x Quadro RTX 5000, 56 GB RAM, 8 vCores (3.3 GHz), 400 GB SSD, 4,000 Mbit/s
    # - rtx5000-84: 3x Quadro RTX 5000, 84 GB RAM, 16 vCores (3.3 GHz), 400 GB SSD, 10,000 Mbit/s
    if name_lower.startswith('rtx5000-'):
        try:
            size = int(name_lower.split('-')[1])
            gpu_count = size // 28
            return gpu_count, gpu_count * 16, 'NVIDIA', 'Turing', 'Quadro RTX 5000 16GB GDDR6'
        except (IndexError, ValueError):
            return 0, None, None, None, None

    # Not a GPU instance
    return 0, None, None, None, None


def _get_storage_type(flavor_name):
    """Determine storage type based on flavor name.

    Storage specifications verified from OVHcloud Cloud Manager (retrieved 2025-11-17).

    Returns:
        StorageType: NVME_SSD for NVMe-based instances, SSD for SATA SSD instances

    Storage Type Mapping:
        - B3 series: NVMe SSD (50-400 GB NVMe)
        - C3 series: NVMe SSD (50-400 GB NVMe)
        - R3 series: NVMe SSD (50-400 GB NVMe)
        - D2 series: NVMe SSD (25-50 GB NVMe)
        - I1 series: Mixed - SSD boot + NVMe data drives
        - B2 series: SATA SSD (50-400 GB SSD)
        - C2 series: SATA SSD (50-400 GB SSD)
        - R2 series: SATA SSD (50-400 GB SSD)
        - BM series: SATA SSD (2x 960 GB SSD)
        - GPU T1/T2 series: NVMe SSD (300-800 GB NVMe, some with NVMe Passthrough)
        - GPU L4/L40S/A10/H100 series: NVMe SSD (400 GB NVMe, some with NVMe Passthrough)
        - GPU RTX5000 series: SATA SSD (400 GB)
        - GPU A100 series: Storage type not specified
    """
    name_lower = flavor_name.lower()

    # 3rd generation instances (B3, C3, R3) - NVMe storage
    if name_lower.startswith(('b3-', 'c3-', 'r3-')):
        return StorageType.NVME_SSD

    # Discovery instances (D2) - NVMe storage
    if name_lower.startswith('d2-'):
        return StorageType.NVME_SSD

    # Storage optimized (I1) - Mixed SSD + NVMe
    # API reports combined, using SSD as it's the boot disk type
    if name_lower.startswith('i1-'):
        return StorageType.SSD

    # 2nd generation instances (B2, C2, R2) - SATA SSD storage
    if name_lower.startswith(('b2-', 'c2-', 'r2-')):
        return StorageType.SSD

    # Bare Metal instances - SATA SSD (2x 960 GB SSD)
    if name_lower.startswith('bm-'):
        return StorageType.SSD

    # Tesla V100/V100S (T1/T2 series) - NVMe
    if name_lower.startswith(('t1-', 't1-le-', 't2-', 't2-le-')):
        return StorageType.NVME_SSD

    # L4, L40S, A10 series - NVMe
    if name_lower.startswith(('l4-', 'l40s-', 'a10-')):
        return StorageType.NVME_SSD

    # H100 series - NVMe with Passthrough
    if name_lower.startswith('h100-'):
        return StorageType.NVME_SSD

    # RTX 5000 series - SATA SSD
    if name_lower.startswith('rtx5000-'):
        return StorageType.SSD

    # A100 series - Storage type not specified
    # Default to SSD for safety
    return StorageType.SSD


def inventory_compliance_frameworks(vendor):
    """Manual list of known compliance frameworks on OVHcloud.
    Verified on ovhcloud.com:
    - ISO/IEC 27001/27017/27018 (page: /en/compliance/iso-27001-27017-27018/)
    - SOC 1, SOC 2, SOC 3 with SOC 2 Type 2 details (page: /en/compliance/soc-1-2-3/)
    Our lookup currently defines: "iso27001" and "soc2t2".
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
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id,
        [
            "iso27001",  # ISO/IEC 27001
            "soc2t2",  # SOC 2 Type 2
        ],
    )


def inventory_regions(vendor):
    """Fetch available OVHcloud Public Cloud regions.

    Source: https://www.ovhcloud.com/en/public-cloud/regions-availability/
            Section: "OpenStack regions and geographical sites"

    Official Documentation:
        Region codes mapped from OVHcloud's official regions page:
        - EMEA: SBG (Strasbourg), GRA (Gravelines), RBX (Roubaix), WAW (Warsaw),
                DE/LIM (Frankfurt), UK/ERI (London), PAR (Paris)
        - North America: BHS (Beauharnois/Montreal), HIL (Hillsboro/Seattle),
                        VIN (Vint Hill/Washington DC), TOR (Toronto)
        - Asia Pacific: SGP (Singapore), SYD (Sydney), MUM (Mumbai)
    """
    items = []
    regions = _get_regions_from_catalog()

    # Map OVHcloud region codes to country codes
    # Source: https://www.ovhcloud.com/en/public-cloud/regions-availability/
    region_country_mapping = {
        # Europe (EMEA)
        'SBG': 'FR',  # Strasbourg, France
        'GRA': 'FR',  # Gravelines, France
        'RBX': 'FR',  # Roubaix, France
        'PAR': 'FR',  # Paris, France (3-AZ)
        'ERI': 'GB',  # London (Erith), United Kingdom
        'LIM': 'DE',  # Frankfurt (Limburg), Germany
        'WAW': 'PL',  # Warsaw, Poland
        'DE': 'DE',  # Frankfurt, Germany
        'UK': 'GB',  # London, United Kingdom
        # North America
        'BHS': 'CA',  # Beauharnois (Montreal), Quebec, Canada
        'TOR': 'CA',  # Toronto, Canada
        'HIL': 'US',  # Hillsboro (Seattle/Portland), Oregon, USA
        'VIN': 'US',  # Vint Hill (Washington DC), Virginia, USA
        # Asia-Pacific
        'SGP': 'SG',  # Singapore
        'SYD': 'AU',  # Sydney, Australia
        'MUM': 'IN',  # Mumbai, India
    }

    # Coordinates for OVHcloud datacenter locations
    # Source: Mixed - Exact datacenter addresses from Google Maps search (retrieved 2025-11-17)
    #         and city-level coordinates from Google Maps Geocoding API
    # Note: OVHcloud region page confirms Frankfurt (Limburg), Warsaw (Ożarów), London (Erith)
    #       as specific datacenter locations opened in 2016
    region_coordinates = {
        # Exact datacenter locations from Google Maps (address-level precision)
        'SBG': (48.5854388, 7.7974307),  # Strasbourg - 9 Rue du Bass. de l'Industrie, 67000
        'GRA': (51.0166852, 2.1551437),  # Gravelines - 1 Rte de la Frm Masson, 59820 Gravelines
        'RBX': (50.691834, 3.2003148),  # Roubaix - 2 Rue Kellermann, 59100 (HQ)
        'PAR': (48.8885363, 2.3755977),  # Paris - 12 Rue Riquet, 75019
        'ERI': (51.4915264, 0.1668186),  # London (Erith) - 8 Viking Way, Erith DA8 1EW, UK
        'WAW': (52.2077264, 20.8080621),  # Warsaw (Ożarów) - Kazimierza Kamińskiego 6, 05-850 Ożarów Mazowiecki
        'BHS': (45.3093037, -73.8965535),  # Beauharnois - 50 Rue de l'Aluminerie, QC J6N 0C2
        'SGP': (1.3177101, 103.893902),  # Singapore - 1 Paya Lebar Link, PLQ 1, #11-02, 408533
        'TOR': (43.4273216, -80.3726843),  # Toronto (Cambridge) - 17 Vondrau Dr, Cambridge, ON N3E 1B8
        'VIN': (38.7474561, -77.6744531),  # Vint Hill (Warrenton) - 6872 Watson Ct, Warrenton, VA 20187, USA
        # City-level coordinates from Google Maps Geocoding API (approximate - no exact DC address found)
        'LIM': (50.1109221, 8.6821267),  # Frankfurt (Limburg), Germany - city-level
        'UK': (51.4915264, 0.1668186),  # London, United Kingdom - using Erith coordinates as proxy
        'DE': (50.1109221, 8.6821267),  # Frankfurt, Germany - city-level
        'HIL': (45.520137, -122.9898308),  # Hillsboro, Oregon, USA - city-level
        'SYD': (-33.8727409, 151.2057136),  # Sydney, Australia - city-level
        'MUM': (12.9062205, 77.6062467),  # Bengaluru office as proxy for Mumbai - city-level
    }

    # Exact addresses for datacenters where known
    # Source: Google Maps search (retrieved 2025-11-17)
    # Format: street + city (and state/province where relevant); zip/postal codes are stored separately in region_zip_codes
    region_addresses = {
        'SBG': '9 Rue du Bass. de l\'Industrie, Strasbourg',
        'GRA': '1 Rte de la Frm Masson, Gravelines',
        'RBX': '2 Rue Kellermann, Roubaix',
        'PAR': '12 Rue Riquet, Paris',
        'BHS': '50 Rue de l\'Aluminerie, Beauharnois, QC',
        'WAW': 'Kazimierza Kamińskiego 6, Ożarów Mazowiecki',
        'SGP': '1 Paya Lebar Link, PLQ 1, Paya Lebar Quarter, #11-02, Singapore',
        'TOR': '17 Vondrau Dr, Cambridge, ON',
        'ERI': '8 Viking Way, Erith',
        'VIN': '6872 Watson Ct, Warrenton, VA',
    }

    # Zip/postal codes for datacenters where known
    region_zip_codes = {
        'SBG': '67000',
        'GRA': '59820',
        'RBX': '59100',
        'PAR': '75019',
        'BHS': 'J6N 0C2',
        'WAW': '05-850',
        'SGP': '408533',
        'TOR': 'N3E 1B8',
        'ERI': 'DA8 1EW',
        'VIN': '20187',
    }

    # State/province mapping
    region_state_mapping = {
        'BHS': 'Quebec',
        'TOR': 'Ontario',
        'VIN': 'Virginia',
        'HIL': 'Oregon',
    }

    for region_code in regions:
        base_code, city = _get_base_region_and_city(region_code)
        country_id = region_country_mapping.get(base_code)
        state = region_state_mapping.get(base_code)
        coords = region_coordinates.get(base_code)
        lon = coords[1] if coords else None
        lat = coords[0] if coords else None
        address = region_addresses.get(base_code)
        zip_code = region_zip_codes.get(base_code)

        items.append({
            "vendor_id": vendor.vendor_id,
            "region_id": region_code,
            "name": region_code,
            "api_reference": region_code,
            "display_name": f"{city} ({region_code})" if city else region_code,
            "aliases": [base_code],
            "country_id": country_id,
            "state": state,
            "city": city,
            "address_line": address,
            "zip_code": zip_code,
            "lon": lon,
            "lat": lat,
            "founding_year": None,
            "green_energy": None,
        })

    return items


def inventory_zones(vendor):
    """List all regions as availability zones.

    OVHcloud API doesn't expose zones as a separate entity.
    Most regions are single-zone. Multi-AZ regions (like Paris with 3-AZ)
    handle zone distribution automatically at the instance level, so creating 1-1
    dummy zones reusing the region id and name, like in Hetzner Cloud.
    Use city names from region mapping for better display names.
    """

    items = []
    regions = _get_regions_from_catalog()
    for region in regions:
        _, city = _get_base_region_and_city(region)
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region,
                "zone_id": region,
                "name": city,
                "api_reference": city,
                "display_name": city,
            }
        )
    return items


def inventory_servers(vendor):
    """Fetch available OVHcloud Public Cloud flavors (server types)."""
    items = []
    servers = _get_servers_from_catalog()
    flavors = {}
    for server in servers:
        flavor_name = server.get('invoiceName', None)
        if flavor_name and flavor_name not in flavors:
            flavors[flavor_name] = server

    for server_id, server in flavors.items():
        blobs = server.get('blobs', {})
        if not blobs:
            continue  # Skip if no blob data available
        commercial = blobs.get('commercial', {})
        technical = blobs.get('technical', {})
        brick_subtype = commercial.get('brickSubtype', '')
        name = commercial.get('name', server_id)
        display_name = brick_subtype if brick_subtype else name
        server_family = _get_server_family(server_id)
        cpu = technical.get('cpu', {})
        gpu = technical.get('gpu', {})
        bandwidth = technical.get('bandwidth', {})
        bandwidth_level = bandwidth.get('level', None)
        memory = technical.get('memory', {})
        memory_size_gb = memory.get('size', None)
        memory_size = memory_size_gb * MIB_PER_GIB if memory_size_gb else None
        cpu_manufacturer = cpu.get('brand', None)
        cpu_model = cpu.get('model', None)
        cpu_speed = cpu.get('frequency', None)
        _cpu_manufacturer, _cpu_model, _cpu_speed = _get_cpu_info(server_id)
        if not cpu_manufacturer and _cpu_manufacturer:
            cpu_manufacturer = _cpu_manufacturer
        if not cpu_model and _cpu_model:
            cpu_model = _cpu_model
        if not cpu_speed and _cpu_speed:
            cpu_speed = _cpu_speed
        cpu_allocation = CpuAllocation.DEDICATED if cpu.get('type', None) == 'core' else CpuAllocation.SHARED
        vcpus = cpu.get('cores', 0) if cpu_allocation == CpuAllocation.SHARED else cpu.get('threads',
                                                                                           cpu.get('cores', 0))
        cpu_cores = cpu.get('cores', None) if cpu_allocation == CpuAllocation.DEDICATED else None
        gpu_count = gpu.get('number', 0)
        gpu_memory_per_gpu = gpu.get('memory').get('size', 0) if gpu.get('memory') else None
        gpu_memory_total_gb = gpu_memory_per_gpu * gpu_count if gpu_memory_per_gpu and gpu_count else None
        gpu_model = f"{gpu.get('model')} {gpu.get('memory').get('interface')}" if gpu else None
        _gpu_count, _gpu_memory_total_gb, gpu_manufacturer, gpu_family, _gpu_model = _get_gpu_info(server_id)
        if not gpu_count and _gpu_count:
            gpu_count = _gpu_count
        if not gpu_memory_total_gb and _gpu_memory_total_gb:
            gpu_memory_total_gb = _gpu_memory_total_gb
        if not gpu_model and _gpu_model:
            gpu_model = _gpu_model
        gpu_memory_total = gpu_memory_total_gb * MIB_PER_GIB if gpu_memory_total_gb else None
        has_nvme = any(
            'nvme' in disk.get('technology', '').lower() for disk in technical.get('storage', {}).get('disks', []))
        storage_type = StorageType.NVME_SSD if has_nvme else StorageType.SSD
        _storage_type = _get_storage_type(server_id)
        if storage_type == StorageType.SSD and _storage_type == StorageType.NVME_SSD:
            storage_type = _storage_type
        storage_size = sum([disk.get('number', 1) * disk.get('capacity', 0) for disk in
                            technical.get('storage', {}).get('disks', [])])

        items.append({
            "vendor_id": vendor.vendor_id,
            "server_id": server_id,
            "name": display_name,
            "api_reference": server_id,
            "display_name": display_name,
            "description": None,  # TODO: add capabilities info?
            "family": server_family,
            "vcpus": vcpus,
            # Verified from lscpu on B3-8 instance (2025-11-17)
            "hypervisor": "KVM" if cpu_allocation == CpuAllocation.SHARED else None,
            "cpu_allocation": cpu_allocation,
            "cpu_cores": cpu_cores,
            "cpu_speed": cpu_speed,
            "cpu_architecture": CpuArchitecture.X86_64,  # All OVHcloud instances use x86_64
            "cpu_manufacturer": cpu_manufacturer,
            "cpu_family": None,
            "cpu_model": cpu_model,
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
            "gpu_memory_min": gpu_memory_total,  # For GPU instances, min = total?
            "gpu_memory_total": gpu_memory_total,
            "gpu_manufacturer": gpu_manufacturer,
            "gpu_family": gpu_family,
            "gpu_model": gpu_model,
            "gpus": [],
            "storage_size": storage_size,  # Local disk in GB
            "storage_type": storage_type,  # Determined from flavor specifications
            "storages": [],
            "network_speed": bandwidth_level,
            "inbound_traffic": 0,  # TODO
            "outbound_traffic": 0,  # TODO
            "ipv4": 1,  # Each instance gets at least one IPv4
            "status": Status.ACTIVE,  # After filtering for available flavors only
        })

    return items


def inventory_server_prices(vendor):
    """Fetch server pricing and regional availability."""
    items = []
    client = _client()
    catalog = _get_catalog(client)
    currency = catalog.get('locale', {}).get('currencyCode', 'USD')
    servers = _get_servers_from_catalog()
    for server in servers:
        plancode = server.get('planCode', '')
        server_id = server.get('invoiceName', '')
        blobs = server.get('blobs', {})
        if not blobs:
            continue  # Skip if no blob data available
        if plancode.endswith('.LZ.AF') or plancode.endswith('.LZ.EU') or plancode.endswith('.3AZ') or plancode.endswith(
                '.LZ.EUROZONE'):
            continue  # TODO: skip variants for now
        regions = server.get('configurations', [])[0].get('values', []) if server.get('configurations') else []
        price = server.get('pricings', [])[0].get('price', None) if server.get('pricings') else None
        interval_unit_str = server.get('pricings', [])[0].get('intervalUnit', '') if server.get('pricings') else ''
        interval_unit = PriceUnit.MONTH if interval_unit_str == 'month' else PriceUnit.HOUR
        status = Status.ACTIVE if "active" in blobs.get('tags', []) else Status.INACTIVE
        technical = blobs.get('technical', {})
        os = technical.get('os', {}).get('family', 'linux')
        if price:
            price = price / MICROCENTS_PER_CURRENCY_UNIT
        for region in regions:
            items.append({
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
                "currency": currency,
                "status": status,
            })
    return items


def inventory_server_prices_spot(vendor):
    """There are no spot instances in OVHcloud Public Cloud."""
    return []


def inventory_storages(vendor):
    """Inventory OVHCloud storage types dynamically from catalog."""
    items = []
    items_dict = {}
    storages = _get_storages_from_catalog()

    for storage in storages:
        if not storage.get('invoiceName', '') in items_dict:
            items_dict[storage.get('invoiceName', '')] = storage

    for storage_id, storage in items_dict.items():
        blobs = storage.get('blobs', {})
        commercial = blobs.get('commercial', {})
        technical = blobs.get('technical', {})

        # Determine storage type based on brick and name
        brick = commercial.get('brick', '')
        brick_subtype = commercial.get('brickSubtype', '')
        name = commercial.get('name', storage_id)

        # Initialize specs
        max_iops = None
        max_size = None

        # Extract volume specifications
        if brick == 'volume':
            volume_specs = technical.get('volume', {})

            # Capacity limits (in GiB)
            capacity = volume_specs.get('capacity', {})
            max_size = capacity.get('max')

            # IOPS specifications
            iops_specs = volume_specs.get('iops', {})
            if iops_specs:
                max_iops = iops_specs.get('level')
                # 'guaranteed' field indicates if IOPS is guaranteed (True) or best-effort (False)

        # Display name from brick subtype or name
        display_name = brick_subtype if brick_subtype else name

        items.append({
            "storage_id": storage_id.replace(' ', '_'),  # fix "bandwidth_storage in" invoiceName
            "vendor_id": vendor.vendor_id,
            "name": display_name,
            "description": None,
            "storage_type": StorageType.NETWORK,
            "max_iops": max_iops,
            "max_throughput": None,
            "min_size": None,
            "max_size": max_size,
        })

    return items


def inventory_storage_prices(vendor):
    """Extract storage prices from OVHCloud catalog."""
    items = []
    catalog = _get_catalog(_client())
    storages = _get_storages_from_catalog()
    currency = catalog.get('locale', {}).get('currencyCode', 'USD')
    for storage in storages:
        plancode = storage.get('planCode', '')
        if plancode.endswith('.LZ') or plancode.endswith('.3AZ') or plancode.endswith('.LZ.EU') or plancode.endswith(
                '.LZ.AF'):
            continue  # TODO: skip variants for now
        regions = storage.get('configurations', [])[0].get('values', []) if storage.get('configurations') else []
        price = storage.get('pricings', [])[0].get('price', None) if storage.get('pricings') else None
        if price:
            description = storage.get('pricings', [])[0].get('description', '') if storage.get('pricings') else ''
            is_hourly = 'hourly' in description
            price = price * HOURS_PER_MONTH if is_hourly else price
            price = price / MICROCENTS_PER_CURRENCY_UNIT
        for region in regions:
            items.append({
                "vendor_id": vendor.vendor_id,
                "region_id": region,
                # fix "bandwidth_storage in" invoiceName
                "storage_id": storage.get('invoiceName', '').replace(' ', '_'),
                "unit": PriceUnit.GB_MONTH,
                "price": price,
                "currency": currency,
            })

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
