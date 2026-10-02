from functools import cache
from os import environ
from re import compile as recompile

from cachier import cachier
from upcloud_api import CloudManager

from ..inspector import _standardize_gpu_family, _standardize_gpu_model
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
    DatabaseStorageScope,
    DatabaseWireProtocol,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)
from ..utils import _GIB_TO_GB, _HOURS_PER_MONTH, _MIB_PER_GIB, jsoned_hash

# ##############################################################################
# Cached client wrappers


@cache
def _client() -> CloudManager:
    """Authorized UpCloud client using the `UPCLOUD_USERNAME` and `UPCLOUD_PASSWORD` env vars."""
    try:
        username = environ["UPCLOUD_USERNAME"]
    except KeyError:
        raise KeyError("Missing environment variable: UPCLOUD_USERNAME")
    try:
        password = environ["UPCLOUD_PASSWORD"]
    except KeyError:
        raise KeyError("Missing environment variable: UPCLOUD_PASSWORD")
    manager = CloudManager(username, password)
    manager.authenticate()
    return manager


def _get_zones() -> dict:
    """List available zones (GET /1.3/zone).

    Reference: <https://developers.upcloud.com/1.3/5-zones/>
    """
    # example List zones response:
    # {
    #     'zones': {
    #         'zone': [
    #             {
    #                 'description': 'Sydney #1',
    #                 'id': 'au-syd1',
    #                 'public': 'yes'
    #             },
    #             {
    #                 'description': 'Frankfurt #1',
    #                 'id': 'de-fra1',
    #                 'public': 'yes'
    #             },
    #             # ...
    #         ]
    #     }
    # }
    return _client().get_zones()


def _get_server_plans() -> dict:
    """List available server plans (GET /1.3/plan).

    Reference: <https://developers.upcloud.com/1.3/7-plans/>
    """
    # example List available plans response:
    # {
    #     'plans': {
    #         'plan': [
    #             {
    #                 'core_number': 1,
    #                 'current_offering': 'yes',
    #                 'family': 'premium',
    #                 'memory_amount': 2048,
    #                 'name': 'PREMIUM-1xCPU-2GB',
    #                 'public_traffic_out': 1024,
    #                 'storage_size': 25,
    #                 'storage_tier': 'maxiops'
    #             },
    #             {
    #                 'core_number': 8,
    #                 'current_offering': 'yes',
    #                 'family': 'gpu',
    #                 'gpu_amount': 1,
    #                 'gpu_model': 'NVIDIA L40S',
    #                 'memory_amount': 65536,
    #                 'name': 'GPU-8xCPU-64GB-1xL40S',
    #                 'public_traffic_out': 12288,
    #                 'storage_size': 0,
    #                 'storage_tier': None
    #             },
    #             # ...
    #         ]
    #     }
    # }
    return _client().get_server_plans()


def _get_prices() -> dict:
    """List resource prices (GET /1.3/price).

    Reference: <https://developers.upcloud.com/1.3/4-pricing/>
    """
    # example List prices response:
    # {
    #     'prices': {
    #         'currency': 'EUR',
    #         'zone': [
    #             {
    #                 'name': 'au-syd1',
    #                 'firewall': {
    #                     'amount': 1,
    #                     'price': 0
    #                 },
    #                 'ipv4_address': {
    #                     'amount': 1,
    #                     'price': 0.4812
    #                 },
    #                 'ipv6_address': {
    #                     'amount': 1,
    #                     'price': 0
    #                 },
    #                 'public_ipv4_bandwidth_in': {
    #                     'amount': 1,
    #                     'price': 0
    #                 },
    #                 'public_ipv4_bandwidth_out': {
    #                     'amount': 1,
    #                     'price': 1
    #                 },
    #                 'server_core': {
    #                     'amount': 1,
    #                     'price': 1.12
    #                 },
    #                 'server_memory': {
    #                     'amount': 256,
    #                     'price': 0.14
    #                 },
    #                 'server_plan_1xCPU-1GB': {
    #                     'amount': 1,
    #                     'price': 1.1309
    #                 },
    #                 'server_plan_GPU-8xCPU-64GB-1xL40S': {
    #                     'amount': 1,
    #                     'price': 111.1607
    #                 },
    #                 'server_plan_GPU-SPOT-8xCPU-64GB-1xL4': {
    #                     'amount': 1,
    #                     'price': 57
    #                 },
    #                 'storage_hdd': {
    #                     'amount': 1,
    #                     'price': 0.0078
    #                 },
    #                 'storage_maxiops': {
    #                     'amount': 1,
    #                     'price': 0.031
    #                 },
    #                 'storage_standard': {
    #                     'amount': 1,
    #                     'price': 0.0118
    #                 },
    #                 'managed_database_1x1xCPU-1GB-10GB': {
    #                     'amount': 1,
    #                     'price': 1.1111
    #                 },
    #                 'managed_database_tiered_storage_standard': {
    #                     'amount': 1,
    #                     'price': 0.0055
    #                 },
    #                 # ...
    #             },
    #             # ...
    #         ]
    #     }
    # }
    return _client().get_prices()


def _get_pg_service_type() -> dict:
    """PostgreSQL managed database type details (GET /1.3/database/service-types/pg).

    Reference: <https://developers.upcloud.com/1.3/16-managed-database/>
    """
    # example Get Managed Database type details response:
    # {
    #     'name': 'pg',
    #     'description': 'PostgreSQL - High-performance relational database with advanced extensions',
    #     'latest_available_version': '18.6',
    #     'service_plans': [
    #         {
    #             'backup_config': {
    #                 'interval': 24,
    #                 'max_count': 15,
    #                 'recovery_mode': 'pitr'
    #             },
    #             'backup_config_pg': {
    #                 'interval': 24,
    #                 'max_count': 15,
    #                 'recovery_mode': 'pitr'
    #             },
    #             'node_count': 2,
    #             'zones': {
    #                 'zone': [
    #                     {
    #                         'name': 'au-syd1'
    #                     },
    #                     {
    #                         'name': 'de-fra1'
    #                     },
    #                     # ...
    #                 ]
    #             },
    #             'plan': '2x16xCPU-64GB-1000GB',
    #             'core_number': 16,
    #             'storage_size': 1024000,
    #             'storage_step_size': 10240,
    #             'storage_cap_size': 5120000,
    #             'memory_amount': 65536,
    #             'components': {
    #                 'compute': {
    #                     'cpu': 16,
    #                     'memory_gb': 64,
    #                     'name': '16CPU-64GB',
    #                     'node_count': 2
    #                 },
    #                 'storage': {
    #                     'dynamic_storage_supported': True,
    #                     'included_gib': 1000
    #                 }
    #             },
    #             'legacy': True
    #         },
    #         # ...
    #     ],
    #     'properties': {
    #         'version': {
    #             'title': 'PostgreSQL major version',
    #             'type': [
    #                 'string',
    #                 'null'
    #             ],
    #             'enum': [
    #                 '15',
    #                 '16',
    #                 '17',
    #                 '18'
    #             ]
    #         },
    #         'ip_filter': {
    #             'default': [],
    #             'title': 'IP filter',
    #             'type': 'array',
    #             'items': {
    #                 'example': [
    #                     '10.0.0.0/24'
    #                 ],
    #                 'maxLength': 18,
    #                 'title': 'CIDR address block',
    #                 'type': 'string'
    #             },
    #             'maxItems': 1024,
    #             'description': "Allow incoming connections from CIDR address block, e.g. '10.20.0.0/16'"
    #         },
    #         'automatic_utility_network_ip_filter': {
    #             'default': True,
    #             'title': 'Automatic utility network IP Filter',
    #             'type': 'boolean',
    #             'description': 'Automatically allow connections from servers in the utility network within the same zone'
    #         },
    #         'service_log': {
    #             'example': True,
    #             'title': 'Service logging',
    #             'type': [
    #                 'boolean',
    #                 'null'
    #             ],
    #             'description': 'Store logs for the service so that they are available in the HTTP API and console.'
    #         },
    #         'pgbouncer': {
    #             'title': 'PGBouncer connection pooling settings',
    #             'type': 'object',
    #             'properties': {
    #                 'autodb_pool_mode': {
    #                     'title': 'PGBouncer pool mode',
    #                     'type': 'string',
    #                     'enum': [
    #                         'transaction',
    #                         'session',
    #                         'statement'
    #                     ]
    #                 },
    #                 # ...
    #             },
    #             'description': 'System-wide settings for pgbouncer.'
    #         },
    #         'pgaudit': {
    #             'title': 'PGAudit settings',
    #             'type': 'object',
    #             'properties': {
    #                 'feature_enabled': {
    #                     'title': 'Enable pgaudit extension.',
    #                     'type': 'boolean',
    #                     'description': 'Enable pgaudit extension. When enabled, pgaudit extension will be automatically installed.Otherwise, extension will be uninstalled but auditing configurations will be preserved.'
    #                 },
    #                 # ...
    #             },
    #             'description': 'System-wide settings for the pgaudit extension.'
    #         },
    #         'pg_stat_monitor_enable': {
    #             'default': False,
    #             'title': 'Enable pg_stat_monitor extension if available for the current cluster',
    #             'type': 'boolean',
    #             'description': 'Enable the pg_stat_monitor extension. Changing this parameter causes a service restart. When this extension is enabled, pg_stat_statements results for utility commands are unreliable'
    #         },
    #         # ...
    #     }
    # }
    return _client().api.get_request("/database/service-types/pg")


def _get_database_plans() -> dict:
    """List componentised database plans (GET /1.3/database/plans).

    Reference: <https://developers.upcloud.com/1.3/16-managed-database/>
    """
    # example List database plans response:
    # {
    #     'service_types': [
    #         {
    #             'type': 'pg',
    #             'latest_version': '18',
    #             'componentised': True,
    #             'zones': ['de-fra1', 'fi-hel1'],
    #             'backup_tiers': ['mini', 'regular', 'extended'],
    #             'node_counts': [1, 2, 3],
    #             'compute_shapes': [
    #                 {
    #                     'compute': 'rdb.standard.2CPU-8GB',
    #                     'family': 'standard',
    #                     'cpu': 2,
    #                     'memory_gb': 8,
    #                     'dynamic_storage_supported': True,
    #                     'node_counts': [1, 2, 3],
    #                     'backups': ['regular', 'extended'],
    #                     'storage': {
    #                         'step_gib': 10,
    #                         'dynamic_max_multiplier': 4,
    #                         'total_cap_gib': 4096,
    #                         'options': [
    #                             {'base_gib': 80, 'max_gib': 320},
    #                             {'base_gib': 160, 'max_gib': 640},
    #                         ],
    #                     },
    #                 },
    #                 {
    #                     'compute': 'rdb.development.1CPU-1GB',
    #                     'family': 'development',
    #                     'cpu': 1,
    #                     'memory_gb': 1,
    #                     'dynamic_storage_supported': True,
    #                     'node_counts': [1],
    #                     'backups': ['mini'],
    #                     'storage': {
    #                         'step_gib': 10,
    #                         'dynamic_max_multiplier': 4,
    #                         'total_cap_gib': 2560,
    #                         'options': [{'base_gib': 10, 'max_gib': 40}],
    #                     },
    #                 },
    #                 {
    #                     'compute': 'rdb.memory.64CPU-512GB',
    #                     'family': 'memory',
    #                     'cpu': 64,
    #                     'memory_gb': 512,
    #                     'dynamic_storage_supported': True,
    #                     'node_counts': [1, 2, 3],
    #                     'backups': ['regular', 'extended'],
    #                     'storage': {
    #                         'step_gib': 10,
    #                         'dynamic_max_multiplier': 4,
    #                         'total_cap_gib': 15360,
    #                         'options': [{'base_gib': 1000, 'max_gib': 4000}],
    #                     },
    #                 },
    #             ],
    #         },
    #     ]
    # }
    return _client().api.get_request("/database/plans")


# Componentised plan families (Developer / Standard / High Memory).
# https://upcloud.com/global/pricing/
_DATABASE_PLAN_FAMILIES = {
    "development": "Developer",
    "standard": "Standard",
    "memory": "High Memory",
}
# Included PITR retention by backup tier name from /database/plans.
# https://upcloud.com/global/pricing/
_DATABASE_BACKUP_RETENTION_DAYS = {
    "mini": 3,
    "regular": 15,
    "extended": 31,
}
# Multi-node compute billing: 2nd node -10%, 3rd node -30%.
# https://upcloud.com/global/pricing/
# https://upcloud.com/global/blog/flexible-scaling-affordable-zero-hidden-fees-updated-managed-database-plans/
_DATABASE_HA_NODE_PRICE_FACTOR = {
    1: 1.0,
    2: 1.9,
    3: 2.6,
}


@cachier(hash_func=jsoned_hash, separate_files=True)
def _get_device_region_availability(region_id: str, device_type: str = "gpu") -> dict:
    """Return available passthrough devices (GET /1.3/device/availability).

    See https://upcloudltd.github.io/upcloud-openapi-spec/api/device#get-available-passthrough-devices
    """
    # example Get available passthrough devices response:
    # {
    #     'fi-hel2': {
    #         'gpu_plans': {
    #             'GPU-12xCPU-128GB-1xL4': {
    #                 'amount': 1
    #             },
    #             'GPU-12xCPU-128GB-1xL40S': {
    #                 'amount': 10
    #             },
    #             # ...
    #         }
    #     }
    # }
    params: dict[str, str] = {"type": device_type}
    params["zone"] = region_id
    return _client().api.get_request("/device/availability", params=params)


def _get_gpu_region_availability(region_id: str) -> dict[str, dict]:
    return (
        _get_device_region_availability(region_id)
        .get(region_id, {})
        .get("gpu_plans", {})
    )


# Block storage tiers. IOPS from docs, MaxIOPS throughput ~400 MB/s (workload-
# dependent). MaxIOPS v2 is in progress and aims ~2–3× that throughput.
# https://upcloud.com/docs/products/block-storage/tiers/
# https://upcloud.com/docs/roadmap/#ready-to-use
UPCLOUD_STORAGES = [
    {
        "id": "hdd",
        "name": "Archive",
        "description": "High-capacity data storage",
        "storage_type": StorageType.HDD,
        "min_size": 1,
        "max_size": 4096,
        "max_iops": 600,
        "max_throughput": None,
    },
    {
        "id": "standard",
        "name": "Standard",
        "description": "General purpose data storage",
        "storage_type": StorageType.SSD,
        "min_size": 1,
        "max_size": 4096,
        "max_iops": 10000,
        "max_throughput": None,
    },
    {
        "id": "maxiops",
        "name": "MaxIOPS",
        "description": "High-performance web servers and applications",
        "storage_type": StorageType.SSD,
        "min_size": 1,
        "max_size": 4096,
        "max_iops": 100000,
        "max_throughput": 400,
    },
]

# ##############################################################################
# Internal helpers


def _parse_server_name(name):
    """Extract server family and description from the server id."""
    name_pattern = recompile(
        r"^(?:(?P<family>[A-Z]+)-)?"
        r"(?:(?P<spot>SPOT)-)?"
        r"(?P<vcpus>[0-9]+)xCPU-"
        r"(?P<memory>[0-9]+)GB"
        r"(?:-(?P<gpu_count>[0-9]+)x(?P<gpu_model>[A-Z][A-Z0-9]*))?"
        r"(?:-(?P<storage_suffix>[0-9]+)GB)?$"
    )
    name_match = name_pattern.match(name)
    if not name_match:
        raise ValueError(f"Server name '{name}' does not match the expected format.")
    data = name_match.groupdict()
    family_mapping = {
        None: "General Purpose",
        "DEV": "Developer",
        "HICPU": "High CPU",
        "HIMEM": "High Memory",
        "GPU": "GPU",
        "STARTER": "Starter",
        "CLOUDNATIVE": "Cloud Native",
        "PREMIUM": "Premium",
    }
    data["family"] = family_mapping.get(data["family"], data["family"])
    description_parts = [f"{data['vcpus']} vCPUs", f"{data['memory']} GiB RAM"]
    if data.get("gpu_count") and data.get("gpu_model"):
        description_parts.append(f"{data['gpu_count']}x {data['gpu_model']}")
    data["description"] = f"{data['family']} ({', '.join(description_parts)})"
    return data


def _upcloud_server_status(vendor, server: dict) -> Status:
    """Map plan current_offering and GPU stock to Server status."""
    if server.get("current_offering") == "no":
        return Status.RETIRED
    if server.get("family") != "gpu":
        return Status.ACTIVE
    for region in vendor.regions:
        amount = (
            _get_gpu_region_availability(region.region_id)
            .get(server["name"], {})
            .get("amount", 0)
        )
        if amount:
            return Status.ACTIVE
    return Status.INACTIVE


_UPCLOUD_GPU_MEMORY_MIB = {
    "L4": 24 * _MIB_PER_GIB,
    "L40S": 48 * _MIB_PER_GIB,
    "H100": 80 * _MIB_PER_GIB,
    "B200": 192 * _MIB_PER_GIB,
}

_UPCLOUD_GPU_FAMILY = {
    "L4": "Ada Lovelace",
    "L40S": "Ada Lovelace",
    "H100": "Hopper",
    "B200": "Blackwell",
}


def _parse_gpu_model(gpu_model: str | None, gpu_count: float = 0) -> dict:
    """Derive GPU inventory fields from the UpCloud gpu_model string."""
    empty = {
        "gpu_memory_min": 0,
        "gpu_memory_total": 0,
        "gpu_manufacturer": None,
        "gpu_family": None,
        "gpu_model": None,
    }
    if not gpu_model:
        return empty

    model = _standardize_gpu_model(gpu_model.strip())
    if not model:
        return empty

    memory_per_gpu = _UPCLOUD_GPU_MEMORY_MIB.get(model)
    manufacturer = "NVIDIA" if gpu_model.strip().upper().startswith("NVIDIA") else None
    family = _standardize_gpu_family({"gpu_model": model}) or _UPCLOUD_GPU_FAMILY.get(
        model
    )
    gpu_memory_total = (
        int(gpu_count * memory_per_gpu) if memory_per_gpu and gpu_count else None
    )

    return {
        "gpu_memory_min": memory_per_gpu,
        "gpu_memory_total": gpu_memory_total,
        "gpu_manufacturer": manufacturer,
        "gpu_family": family,
        "gpu_model": model,
    }


# ##############################################################################
# Public methods to fetch data


def inventory_compliance_frameworks(vendor):
    """Manual list of known compliance frameworks at UpCloud.

    Data collected from their Security and Standards docs at
    <https://upcloud.com/security-privacy>."""
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id,
        ["iso27001"],
    )


def inventory_regions(vendor):
    """List all regions via API call.

    Data manually enriched from <https://upcloud.com/data-centres>."""
    manual_data = {
        "au-syd1": {
            "country_id": "AU",
            "state": "New South Wales",
            "city": "Sydney",
            "founding_year": 2021,
            "green_energy": False,
            "lon": 151.189377,
            "lat": -33.918251,
        },
        "de-fra1": {
            "country_id": "DE",
            "state": "Hesse",
            "city": "Frankfurt",
            "founding_year": 2015,
            "green_energy": True,
            "lon": 8.735120,
            "lat": 50.119190,
        },
        "dk-cph1": {
            "country_id": "DK",
            "city": "Copenhagen",
            "founding_year": 2026,
            "green_energy": True,
            # approximation based on city as the datacenter is not listed on homepage yet
            "lon": 12.57,
            "lat": 55.68,
        },
        "fi-hel1": {
            "country_id": "FI",
            "state": "Uusimaa",
            "city": "Helsinki",
            "founding_year": 2011,
            "green_energy": True,
            "lon": 24.778570,
            "lat": 60.20323,
        },
        "fi-hel2": {
            "country_id": "FI",
            "state": "Uusimaa",
            "city": "Helsinki",
            "founding_year": 2018,
            "green_energy": True,
            "lon": 24.876350,
            "lat": 60.216209,
        },
        "es-mad1": {
            "country_id": "ES",
            "state": "Madrid",
            "city": "Madrid",
            "founding_year": 2020,
            "green_energy": True,
            "lon": -3.6239873,
            "lat": 40.4395019,
        },
        "nl-ams1": {
            "country_id": "NL",
            "state": "Noord Holland",
            "city": "Amsterdam",
            "founding_year": 2017,
            "green_energy": True,
            "lon": 4.8400019,
            "lat": 52.3998291,
        },
        "no-svg1": {
            "country_id": "NO",
            "state": "Rogaland",
            "city": "Stavanger",
            "founding_year": 2025,
            # TODO update when data shared on homepage
            "green_energy": False,
            # approximation based on city - TODO update when info becomes available on the homepage
            "lon": 5.5979374,
            "lat": 58.9487157,
        },
        "pl-waw1": {
            "country_id": "PL",
            "state": "Mazowieckie",
            "city": "Warsaw",
            "founding_year": 2020,
            "green_energy": True,
            "lon": 20.9192823,
            "lat": 52.1905901,
        },
        "se-sto1": {
            "country_id": "SE",
            "state": "Stockholm",
            "city": "Stockholm",
            "founding_year": 2015,
            "green_energy": True,
            "lon": 18.102788,
            "lat": 59.2636708,
        },
        "sg-sin1": {
            "country_id": "SG",
            "state": "Singapore",
            "city": "Singapore",
            "founding_year": 2017,
            "green_energy": True,
            "lon": 103.7022636,
            "lat": 1.3172304,
        },
        "uk-lon1": {
            "country_id": "GB",
            "state": "London",
            "city": "London",
            "founding_year": 2012,
            "green_energy": True,
            # approximate .. probably business address
            "lon": -0.1037341,
            "lat": 51.5232232,
        },
        "us-chi1": {
            "country_id": "US",
            "state": "Illinois",
            "city": "Chicago",
            "founding_year": 2014,
            "green_energy": False,
            "lon": -87.6342056,
            "lat": 41.8761287,
        },
        "us-nyc1": {
            "country_id": "US",
            "state": "New York",
            "city": "New York",
            "founding_year": 2020,
            "green_energy": False,
            "lon": -74.0645536,
            "lat": 40.7834325,
        },
        "us-sjo1": {
            "country_id": "US",
            "state": "California",
            "city": "San Jose",
            "founding_year": 2018,
            "green_energy": False,
            "lon": -121.9754458,
            "lat": 37.3764769,
        },
    }
    items = []
    regions = _get_zones()["zones"]["zone"]
    for region in regions:
        with sentry_capture_or_raise(vendor=vendor):
            if region["public"] == "yes":
                if region["id"] not in manual_data:
                    raise ValueError(f"Missing manual data for {region['id']}")
                region_data = manual_data[region["id"]]
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": region["id"],
                        "name": region["description"],
                        "api_reference": region["id"],
                        "display_name": (
                            region["description"] + f" ({region_data['country_id']})"
                        ),
                        "aliases": [],
                        "country_id": region_data["country_id"],
                        "state": region_data.get("state"),
                        "city": region_data["city"],
                        "address_line": None,
                        "zip_code": None,
                        "lon": region_data["lon"],
                        "lat": region_data["lat"],
                        "founding_year": region_data["founding_year"],
                        "green_energy": region_data["green_energy"],
                    }
                )
    return items


def inventory_zones(vendor):
    """List all regions as availability zones.

    There is no concept of having multiple availability zones withing
    a region (virtual datacenter) at UpCloud, so creating 1-1
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
                "api_reference": region.region_id,
                "display_name": region.name,
            }
        )
    return items


def inventory_servers(vendor):
    """List all server plans from UpCloud API.

    Lifecycle: `current_offering == "no"` -> RETIRED; GPU plans with zero stock
    in `/device/availability` across all regions -> INACTIVE; otherwise ACTIVE.
    See `_upcloud_server_status`.
    """
    servers = _get_server_plans()["plans"]["plan"]
    items = []
    for server in servers:
        with sentry_capture_or_raise(vendor=vendor):
            server_data = _parse_server_name(server["name"])
            if server_data.get("spot"):
                continue
            gpu_count = server.get("gpu_amount", 0)
            gpu_fields = _parse_gpu_model(server.get("gpu_model"), gpu_count)
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "server_id": server["name"],
                    "name": server["name"],
                    "api_reference": server["name"],
                    "display_name": server["name"],
                    "description": server_data["description"],
                    "family": server_data["family"],
                    "vcpus": server["core_number"],
                    # https://upcloud.com/docs/products/cloud-servers/features/cloud-server-system/#virtualisation
                    "hypervisor": "KVM",
                    # no dedicated vCPUs in the public cloud offerings
                    "cpu_allocation": CpuAllocation.SHARED,
                    "cpu_cores": None,
                    "cpu_speed": None,
                    # no known ARM options
                    "cpu_architecture": CpuArchitecture.X86_64,
                    "cpu_manufacturer": None,
                    "cpu_family": None,
                    "cpu_model": None,
                    "cpu_flags": [],
                    "cpus": [],
                    "memory_amount": server["memory_amount"],
                    "memory_generation": None,
                    "memory_speed": None,
                    "memory_ecc": None,
                    "gpu_count": gpu_count,
                    **gpu_fields,
                    "gpus": [],  # TODO fill this array
                    "storage_size": server["storage_size"],
                    "storage_type": (
                        StorageType.SSD if server["storage_tier"] else None
                    ),
                    "storages": [],
                    # TODO: have to implement manual mapping for network_speed related fields
                    "network_speed_baseline": None,
                    "network_speed_max": None,
                    "network_storage_speed_baseline": None,
                    "network_storage_speed_max": None,
                    "inbound_traffic": 0,
                    "outbound_traffic": server["public_traffic_out"],
                    "ipv4": 0 if server_data["family"] == "CLOUDNATIVE" else 1,
                    "status": _upcloud_server_status(vendor, server),
                }
            )
    return items


def inventory_server_prices(vendor):
    items = []
    prices = _get_prices()
    for zone_prices in prices["prices"]["zone"]:
        region_id = zone_prices["name"]
        gpu_region_availability = _get_gpu_region_availability(region_id)
        for k, v in zone_prices.items():
            if not k.startswith("server_plan"):
                continue
            server_plan = k[len("server_plan_") :]
            if "SPOT" in server_plan:
                continue
            if server_plan.startswith("GPU"):
                amount = gpu_region_availability.get(server_plan, {}).get("amount", 0)
                if amount == 0:
                    continue
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region_id,
                    "zone_id": region_id,
                    "server_id": server_plan,
                    "operating_system": "Linux",
                    "allocation": Allocation.ONDEMAND,
                    "unit": PriceUnit.HOUR,
                    "price": v["price"] / 100,
                    "price_upfront": 0,
                    # as per UpCloud FAQ at <https://upcloud.com/docs/getting-started/faq/>:
                    # > All Cloud Server plans on your account are billed hourly up to the monthly rate cap
                    # > and the hourly rate is determined by dividing the monthly rate by 672 hours (28 days).
                    # > However, if your server is online for more than 672 hours in a calendar month,
                    # > we will bill you on the monthly rate.
                    "price_tiered": [
                        {"lower": 0, "upper": 672, "price": v["price"] / 100},
                        {"lower": 673, "upper": "Infinity", "price": 0},
                    ],
                    "currency": "EUR",
                }
            )
    return items


def inventory_server_prices_spot(vendor):
    items = []
    prices = _get_prices()
    for zone_prices in prices["prices"]["zone"]:
        region_id = zone_prices["name"]
        gpu_region_availability = _get_gpu_region_availability(region_id)
        for k, v in zone_prices.items():
            if not k.startswith("server_plan"):
                continue
            server_plan = k[len("server_plan_") :]
            if "SPOT" not in server_plan:
                continue
            if server_plan.startswith("GPU"):
                amount = gpu_region_availability.get(server_plan, {}).get("amount", 0)
                if amount == 0:
                    continue
            server_plan = server_plan.replace("SPOT-", "")
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region_id,
                    "zone_id": region_id,
                    "server_id": server_plan,
                    "operating_system": "Linux",
                    "allocation": Allocation.SPOT,
                    "unit": PriceUnit.HOUR,
                    "price": v["price"] / 100,
                    "price_upfront": 0,
                    "currency": "EUR",
                }
            )
    return items


def inventory_storages(vendor):
    items = []
    for storage in UPCLOUD_STORAGES:
        items.append(
            {
                "storage_id": storage["id"],
                "vendor_id": vendor.vendor_id,
                "name": storage["name"],
                "description": storage["description"],
                "storage_type": storage["storage_type"],
                "max_iops": storage["max_iops"],
                "max_throughput": storage["max_throughput"],
                "min_size": storage["min_size"],
                "max_size": storage["max_size"],
            }
        )
    return items


def inventory_storage_prices(vendor):
    items = []
    prices = _get_prices()
    for zone_prices in prices["prices"]["zone"]:
        for k, v in zone_prices.items():
            if k in ["storage_" + s["id"] for s in UPCLOUD_STORAGES]:
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": zone_prices["name"],
                        "storage_id": k[len("storage_") :],
                        "unit": PriceUnit.GB_MONTH,
                        # UpCloud pricing is per hour, but other providers are per month
                        "price": v["price"] / 100 * 24 * 30,
                        "currency": "EUR",
                    }
                )
    return items


def inventory_traffic_prices(vendor):
    items = []
    prices = _get_prices()
    for zone_prices in prices["prices"]["zone"]:
        for k, v in zone_prices.items():
            if k == "public_ipv4_bandwidth_out":
                for direction in [d for d in TrafficDirection]:
                    items.append(
                        {
                            "vendor_id": vendor.vendor_id,
                            "region_id": zone_prices["name"],
                            "price": (
                                v["price"] / 100
                                if direction == TrafficDirection.OUT
                                else 0
                            ),
                            "price_tiered": [],
                            "currency": "EUR",
                            "unit": PriceUnit.GB_MONTH,
                            "direction": direction,
                        }
                    )
    return items


def inventory_ipv4_prices(vendor):
    items = []
    prices = _get_prices()
    for zone_prices in prices["prices"]["zone"]:
        for k, v in zone_prices.items():
            if k == "ipv4_address":
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": zone_prices["name"],
                        "price": v["price"] / 100,
                        "currency": "EUR",
                        "unit": PriceUnit.HOUR,
                    }
                )
    return items


def _database_shared_capabilities(properties: dict) -> dict:
    """Capability flags shared by legacy and componentised PostgreSQL plans."""
    return {
        # Service settings expose PostgreSQL parameters in `properties`.
        # https://upcloud.com/docs/products/managed-postgresql/configurations/
        "custom_config": True,
        # Product page advertises 70+ pre-installed extensions.
        # https://upcloud.com/global/postgresql-managed-databases/
        "custom_extensions": True,
        # Managed PostgreSQL docs describe encryption at rest.
        # https://upcloud.com/docs/products/managed-postgresql/encryption/
        "disk_encryption": True,
        # Product page advertises automatic updates with zero downtime.
        # https://upcloud.com/global/postgresql-managed-databases/
        "auto_upgrade_versions": True,
        # Connection pools are managed via API; `properties.pgbouncer` exists.
        # https://upcloud.com/docs/guides/postgresql-connection-pool-api/
        "connection_pool": "pgbouncer" in properties,
        # `properties.service_log` and `public_access_prometheus` exist.
        "system_monitoring": "service_log" in properties,
        # `properties.pg_stat_monitor_*` tuning knobs exist.
        "database_monitoring": any(
            key.startswith("pg_stat_monitor") for key in properties
        ),
        # Manual PostgreSQL tuning is documented; no auto-tune API signal.
        # https://upcloud.com/docs/products/managed-postgresql/configurations/
        "autotuning_advice": None,
        "autotuning_apply": None,
        # Managed Databases are advertised with a 99.999% uptime SLA.
        # https://upcloud.com/global/products/managed-databases/
        "sla": 99.999,
        # `properties.ip_filter` and `automatic_utility_network_ip_filter`.
        # https://upcloud.com/docs/products/managed-postgresql/connecting/
        # Utility network (default) and SDN private network attachment.
        # https://upcloud.com/docs/guides/connect-managed-databases-sdn-private-networks/
        # Connection URIs use sslmode=require; CA cert via GET /database/certificate.
        # https://upcloud.com/docs/guides/postgresql-connection-pool-api/
        # https://developers.upcloud.com/1.3/16-managed-database/
        # `properties.pgaudit` enables pgAudit session logging.
        # https://upcloud.com/docs/products/managed-postgresql/supported-extensions/
        "security_features": [
            DatabaseSecurityFeature.IP_FILTERING,
            DatabaseSecurityFeature.PRIVATE_NETWORK,
            DatabaseSecurityFeature.ENFORCED_TLS,
            DatabaseSecurityFeature.AUDIT_LOGGING,
        ],
    }


def _database_ha_from_node_counts(
    node_counts: list[int],
) -> tuple[list[DatabaseHaLevel], list[DatabaseHaStrategy]]:
    """Map supported node counts to HA level/strategy lists (highest first).

    UpCloud standbys accept read-only queries via a separate DNS entry for any
    multi-node plan, so ``node_count >= 2`` maps to ``READABLE_CLUSTER``.
    https://upcloud.com/docs/products/managed-postgresql/high-availability/

    When both 2 and 3 nodes are orderable on one compute shape (componentised
    plans), also include ``PASSIVE_STANDBY`` as the 2-node package price key
    (1.9x vs 2.6x billing tiers).
    https://upcloud.com/global/pricing/
    """
    counts = set(node_counts)
    ha: set[DatabaseHaLevel] = set()
    ha_strategy: set[DatabaseHaStrategy] = set()
    if any(count <= 1 for count in counts):
        ha.add(DatabaseHaLevel.NONE)
        ha_strategy.add(DatabaseHaStrategy.NONE)
    if any(count >= 2 for count in counts):
        ha.add(DatabaseHaLevel.SINGLE_ZONE)
        ha_strategy.add(DatabaseHaStrategy.READABLE_CLUSTER)
        if 2 in counts and any(count >= 3 for count in counts):
            ha_strategy.add(DatabaseHaStrategy.PASSIVE_STANDBY)
    if not ha:
        ha.add(DatabaseHaLevel.NONE)
        ha_strategy.add(DatabaseHaStrategy.NONE)
    return DatabaseHaLevel.ordered(ha), DatabaseHaStrategy.ordered(ha_strategy)


def _match_database_server_id(
    server_ids: set[str],
    cpu: int | None,
    memory_gb: int | None,
    family: str | None = None,
) -> str | None:
    if cpu is None or memory_gb is None:
        return None
    candidates = [f"{cpu}xCPU-{memory_gb}GB"]
    if family == "development":
        candidates.insert(0, f"DEV-{cpu}xCPU-{memory_gb}GB")
    elif family == "memory":
        candidates.insert(0, f"HIMEM-{cpu}xCPU-{memory_gb}GB")
    return next(
        (candidate for candidate in candidates if candidate in server_ids), None
    )


def inventory_databases(vendor):
    """List UpCloud managed PostgreSQL service plans.

    - Componentised Developer/Standard/High Memory shapes from GET /1.3/database/plans.
    - Legacy bundled plans from GET /1.3/database/service-types/pg.
    - Supported versions come from service-types/pg `properties.version.enum`.
    https://developers.upcloud.com/1.3/16-managed-database/
    https://upcloud.com/docs/products/managed-postgresql/configurations/
    https://upcloud.com/global/pricing/
    """
    payload = _get_pg_service_type()
    properties = payload.get("properties", {})
    versions = properties.get("version", {}).get("enum", [])
    shared = _database_shared_capabilities(properties)
    server_ids = {server.server_id for server in vendor.servers}
    items = []

    # Componentised plans: compute is independent of node count (1–3 for Standard /
    # High Memory; Developer is single-node only).
    plans_payload = _get_database_plans()
    for service_type in plans_payload.get("service_types", []):
        if service_type.get("type") not in ("pg", "postgresql"):
            continue
        zones = service_type.get("zones") or []
        status = Status.ACTIVE if zones else Status.INACTIVE
        for shape in service_type.get("compute_shapes", []):
            database_id = shape["compute"]
            family_key = shape.get("family")
            family = _DATABASE_PLAN_FAMILIES.get(family_key, family_key)
            vcpus = shape.get("cpu")
            memory_gb = shape.get("memory_gb")
            memory_amount = memory_gb * _MIB_PER_GIB if memory_gb is not None else None
            node_counts = shape.get("node_counts") or [1]
            ha, ha_strategy = _database_ha_from_node_counts(node_counts)
            storage = shape.get("storage") or {}
            options = storage.get("options") or []
            if options:
                min_base_gib = min(option["base_gib"] for option in options)
                max_gib = max(option["max_gib"] for option in options)
            else:
                min_base_gib = 0
                max_gib = storage.get("total_cap_gib") or 0
            # Storage is billed separately (not bundled into compute).
            # https://upcloud.com/global/pricing/
            if shape.get("dynamic_storage_supported") and max_gib > 0:
                storage_extra_min = (
                    round(min_base_gib * _GIB_TO_GB) if min_base_gib else 0
                )
                storage_extra_max = round(max_gib * _GIB_TO_GB)
            elif min_base_gib:
                storage_extra_min = round(min_base_gib * _GIB_TO_GB)
                storage_extra_max = round(max_gib * _GIB_TO_GB) if max_gib else 0
            else:
                storage_extra_min = 0
                storage_extra_max = 0
            display_name = (
                f"{vcpus}CPU-{memory_gb}GB"
                if vcpus is not None and memory_gb is not None
                else database_id
            )
            description_parts = [
                f"{vcpus} vCPUs" if vcpus else None,
                f"{memory_gb} GiB RAM" if memory_gb else None,
            ]
            description = (
                f"UpCloud PostgreSQL {family} "
                f"({', '.join(filter(None, description_parts))})"
            )
            backup_days = [
                _DATABASE_BACKUP_RETENTION_DAYS[name]
                for name in shape.get("backups") or []
                if name in _DATABASE_BACKUP_RETENTION_DAYS
            ]
            continuous_backups = min(backup_days) if backup_days else None
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "database_id": database_id,
                    "name": database_id,
                    "display_name": display_name,
                    "description": description,
                    "api_reference": database_id,
                    # Componentised plans use plan_compute / plan_node_count /
                    # plan_storage_gib / plan_backups instead of a fixed plan name.
                    # https://developers.upcloud.com/1.3/16-managed-database/
                    "api_reference_object": {
                        "service_type": "pg",
                        "plan_compute": database_id,
                    },
                    "server_id": _match_database_server_id(
                        server_ids, vcpus, memory_gb, family_key
                    ),
                    "engine": DatabaseEngine.POSTGRESQL,
                    "wire_protocol": DatabaseWireProtocol.POSTGRESQL,
                    "engine_versions": versions,
                    "family": family,
                    "vcpus": vcpus,
                    "memory_amount": memory_amount,
                    "storage_size": None,
                    "storage_extra_min": storage_extra_min,
                    "storage_extra_max": storage_extra_max,
                    "storage_extra_autosize": False,
                    "ha": ha,
                    "ha_strategy": ha_strategy,
                    "max_read_replicas": max(max(node_counts) - 1, 0),
                    "scheduled_backups": bool(backup_days),
                    "continuous_backups": continuous_backups,
                    "status": status,
                    **shared,
                }
            )

    # Legacy bundled plans (fixed compute + storage + node count).
    for plan in payload.get("service_plans", []):
        database_id = plan["plan"]
        node_count = plan.get("node_count")
        vcpus = plan.get("core_number")
        memory_amount = plan.get("memory_amount")
        components = plan.get("components", {})
        storage_component = components.get("storage", {})
        # UI/plan names say GB, but API values are GiB
        # https://upcloud.com/docs/products/managed-postgresql/configurations/
        nodes = node_count or 1
        included_gib = storage_component.get("included_gib")
        bundled_gib = (
            int(included_gib)
            if included_gib is not None
            else plan["storage_size"] // _MIB_PER_GIB
        )
        storage_size_gb = round((bundled_gib // nodes) * _GIB_TO_GB)
        storage_step_gb = round(
            (plan["storage_step_size"] // _MIB_PER_GIB) * _GIB_TO_GB
        )
        storage_extra_max_gb = round(
            ((plan["storage_cap_size"] - plan["storage_size"]) // _MIB_PER_GIB // nodes)
            * _GIB_TO_GB
        )
        dynamic_storage_supported = storage_component.get("dynamic_storage_supported")
        if dynamic_storage_supported:
            storage_extra_min = storage_step_gb
            storage_extra_max = storage_extra_max_gb
        else:
            storage_extra_min = 0
            storage_extra_max = 0
        if node_count == 1:
            family = "Single node"
        elif node_count == 2:
            family = "2-node HA"
        else:
            family = "3-node HA"
        compute = components.get("compute", {})
        display_name = compute.get("name")
        cpu = compute.get("cpu")
        memory_gb = compute.get("memory_gb")
        memory_gib = memory_amount / _MIB_PER_GIB
        description_parts = [
            f"{vcpus} vCPUs" if vcpus else None,
            f"{int(memory_gib)} GiB RAM" if memory_gib else None,
            f"{int(storage_size_gb)} GB storage" if storage_size_gb else None,
        ]
        description = (
            f"UpCloud PostgreSQL {family} "
            f"({', '.join(filter(None, description_parts))})"
        )
        backup_cfg = plan.get("backup_config_pg", {})
        if backup_cfg.get("recovery_mode") == "pitr":
            interval = backup_cfg.get("interval")
            max_count = backup_cfg.get("max_count")
            if interval is not None and max_count is not None:
                continuous_backups = (max_count * interval) // 24
            else:
                continuous_backups = None
        else:
            continuous_backups = None
        zones = plan.get("zones", {}).get("zone", [])
        status = Status.ACTIVE if zones else Status.INACTIVE
        ha, ha_strategy = _database_ha_from_node_counts([node_count or 1])

        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "database_id": database_id,
                "name": database_id,
                "display_name": display_name,
                "description": description,
                "api_reference": database_id,
                # Terraform/API provisioning uses `plan` on managed DB resources.
                # https://registry.terraform.io/providers/UpCloudLtd/upcloud/latest/docs/resources/managed_database_postgresql
                "api_reference_object": {
                    "service_type": "pg",
                    "service_plan": database_id,
                },
                # Per-node sizing from service-types/pg `components.compute`.
                "server_id": _match_database_server_id(server_ids, cpu, memory_gb),
                "engine": DatabaseEngine.POSTGRESQL,
                "wire_protocol": DatabaseWireProtocol.POSTGRESQL,
                "engine_versions": versions,
                # Node topology groups from configurations docs (1/2/3 nodes).
                # https://upcloud.com/docs/products/managed-postgresql/configurations/
                "family": family,
                "vcpus": vcpus,
                "memory_amount": memory_amount,
                "storage_size": storage_size_gb,
                # Extra disk is added manually via control panel/API, not when usage grows,
                # `storage_extra_min/max` apply only when `dynamic_storage_supported` is true.
                # https://upcloud.com/docs/changelog/2025-05-26-additional-disk-space-managed-databases/
                "storage_extra_min": storage_extra_min,
                "storage_extra_max": storage_extra_max,
                "storage_extra_autosize": False,
                "ha": ha,
                "ha_strategy": ha_strategy,
                "max_read_replicas": max((node_count or 1) - 1, 0),
                # Plans include daily full backups (`backup_config.interval`).
                # https://upcloud.com/docs/products/managed-postgresql/backups/
                "scheduled_backups": bool(backup_cfg.get("interval")),
                # PITR retention days from backup_config_pg interval * max_count.
                # https://upcloud.com/docs/products/managed-postgresql/backups/
                "continuous_backups": continuous_backups,
                # Plans list orderable zones under `zones.zone`.
                "status": status,
                **shared,
            }
        )
    return items


def inventory_database_prices(vendor):
    """List UpCloud managed PostgreSQL compute prices.

    Legacy plans bill the full cluster under ``managed_database_{plan}``.
    Componentised plans bill per-node compute under
    ``managed_database_compute_{plan_compute}``. Node topology maps to:
    1 node NONE/NONE, 2-node package SINGLE_ZONE/PASSIVE_STANDBY (1.9x),
    3-node package SINGLE_ZONE/READABLE_CLUSTER (2.6x) with published
    multi-node discounts (PASSIVE is only a price key when both 2 and 3
    are orderable on the same compute shape).
    https://upcloud.com/global/pricing/
    """
    items = []
    prices = _get_prices()
    databases = {database.database_id: database for database in vendor.databases}
    legacy_prefix = "managed_database_"
    compute_prefix = "managed_database_compute_"
    currency = prices["prices"].get("currency", "EUR")
    for zone_prices in prices["prices"]["zone"]:
        region_id = zone_prices["name"]
        for k, v in zone_prices.items():
            if k.startswith(compute_prefix):
                database_id = k[len(compute_prefix) :]
                per_node = True
            elif k.startswith(legacy_prefix):
                database_id = k[len(legacy_prefix) :]
                # Skip non-plan meters (storage, backups, …).
                if database_id.startswith(
                    ("tiered_storage", "backup_", "storage_", "compute_")
                ):
                    continue
                per_node = False
            else:
                continue
            database = databases.get(database_id)
            if database is None:
                continue
            base_price = v["price"] / 100
            if per_node:
                strategies = {
                    DatabaseHaStrategy(strategy)
                    for strategy in database.ha_strategy or []
                }
                price_rows = []
                if DatabaseHaStrategy.NONE in strategies:
                    price_rows.append(
                        (
                            DatabaseHaLevel.NONE,
                            DatabaseHaStrategy.NONE,
                            base_price * _DATABASE_HA_NODE_PRICE_FACTOR[1],
                        )
                    )
                if DatabaseHaStrategy.PASSIVE_STANDBY in strategies:
                    price_rows.append(
                        (
                            DatabaseHaLevel.SINGLE_ZONE,
                            DatabaseHaStrategy.PASSIVE_STANDBY,
                            base_price * _DATABASE_HA_NODE_PRICE_FACTOR[2],
                        )
                    )
                if DatabaseHaStrategy.READABLE_CLUSTER in strategies:
                    price_rows.append(
                        (
                            DatabaseHaLevel.SINGLE_ZONE,
                            DatabaseHaStrategy.READABLE_CLUSTER,
                            base_price * _DATABASE_HA_NODE_PRICE_FACTOR[3],
                        )
                    )
            else:
                price_rows = [
                    (database.ha[0], database.ha_strategy[0], base_price),
                ]
            for ha, ha_strategy, price in price_rows:
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": region_id,
                        "database_id": database_id,
                        "allocation": Allocation.ONDEMAND,
                        "ha": ha,
                        "ha_strategy": ha_strategy,
                        "unit": PriceUnit.HOUR,
                        "price": price,
                        "currency": currency,
                    }
                )
    return items


# Managed DB disk tiers from the price list / pricing page.
# Developer (+) legacy additional disk → Standard SSD;
# Standard/High Memory → MaxIOPS.
# https://upcloud.com/global/pricing/
# https://upcloud.com/docs/changelog/2025-05-26-additional-disk-space-managed-databases/
# https://upcloud.com/docs/products/block-storage/tiers/
_DATABASE_STORAGE_TIERS = [
    {
        "database_storage_id": "standard",
        "name": "Standard",
        "description": (
            "Managed database Standard SSD storage "
            "(Developer plans, also additional disk on legacy plans)"
        ),
        "price_key": "managed_database_tiered_storage_standard",
        "max_iops": 10000,
        "max_throughput": None,
    },
    {
        "database_storage_id": "maxiops",
        "name": "MaxIOPS",
        "description": (
            "Managed database MaxIOPS storage (Standard and High Memory plans)"
        ),
        "price_key": "managed_database_tiered_storage_maxiops",
        "max_iops": 100000,
        # Same MaxIOPS block platform as server storage (~400 MB/s today).
        # https://upcloud.com/docs/roadmap/#ready-to-use
        "max_throughput": 400,
    },
]


# Componentised plan families that bill disk on each managed DB storage tier.
# Legacy bundled plans use Standard for additional disk only.
# https://upcloud.com/global/pricing/
_DATABASE_STORAGE_TIER_SHAPE_FAMILIES = {
    "standard": frozenset({"development"}),
    "maxiops": frozenset({"standard", "memory"}),
}


def _database_storage_size_bounds(tier_id: str) -> tuple[int, int] | None:
    """Min/max provisionable managed DB disk (GB) for one storage tier.

    ``standard``: legacy plans + Developer (``development``) shapes.
    ``maxiops``: Standard / High Memory shapes.
    """
    families = _DATABASE_STORAGE_TIER_SHAPE_FAMILIES.get(tier_id)
    if families is None:
        return None
    min_gib: int | None = None
    max_gib = 0
    if tier_id == "standard":
        for plan in _get_pg_service_type().get("service_plans", []):
            nodes = plan.get("node_count") or 1
            included = (
                (plan.get("components") or {}).get("storage", {}).get("included_gib")
            )
            base_gib = (
                int(included)
                if included is not None
                else plan["storage_size"] // _MIB_PER_GIB
            )
            # Per-node floor; cap is cluster storage_cap converted per node.
            floor_gib = base_gib // nodes
            cap_gib = plan["storage_cap_size"] // _MIB_PER_GIB // nodes
            min_gib = floor_gib if min_gib is None else min(min_gib, floor_gib)
            max_gib = max(max_gib, cap_gib)
    for service_type in _get_database_plans().get("service_types", []):
        if service_type.get("type") not in ("pg", "postgresql"):
            continue
        for shape in service_type.get("compute_shapes", []):
            family = shape.get("family")
            if family is None:
                compute = shape.get("compute") or ""
                parts = compute.split(".")
                if len(parts) >= 2 and parts[0] == "rdb":
                    family = parts[1]
            if family not in families:
                continue
            storage = shape.get("storage") or {}
            for option in storage.get("options") or []:
                min_gib = (
                    option["base_gib"]
                    if min_gib is None
                    else min(min_gib, option["base_gib"])
                )
                max_gib = max(max_gib, option["max_gib"])
            total_cap = storage.get("total_cap_gib")
            if total_cap:
                max_gib = max(max_gib, total_cap)
    if min_gib is None or max_gib <= 0:
        return None
    return (
        round(min_gib * _GIB_TO_GB),
        round(max_gib * _GIB_TO_GB),
    )


def inventory_database_storages(vendor):
    """List managed PostgreSQL disk tiers (Standard SSD and MaxIOPS).

    Componentised plans bill all disk via these meters; legacy plans also use
    Standard tiered storage for additional disk above the bundled size.
    Size bounds are per tier (Developer/legacy → Standard; Std/HM → MaxIOPS).
    https://upcloud.com/global/pricing/
    https://upcloud.com/docs/products/block-storage/tiers/
    https://developers.upcloud.com/1.3/16-managed-database/
    """
    items = []
    for tier in _DATABASE_STORAGE_TIERS:
        bounds = _database_storage_size_bounds(tier["database_storage_id"])
        if bounds is None:
            continue
        min_size, max_size = bounds
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "database_storage_id": tier["database_storage_id"],
                "name": tier["name"],
                "description": tier["description"],
                "scope": DatabaseStorageScope.DATA,
                "min_size": min_size,
                "max_size": max_size,
                "max_iops": tier["max_iops"],
                "max_throughput": tier["max_throughput"],
            }
        )
    return items


def inventory_database_storage_prices(vendor):
    """List managed PostgreSQL disk tier prices from the UpCloud zone price list."""
    if not vendor.database_storages:
        return []
    price_key_by_id = {
        tier["database_storage_id"]: tier["price_key"]
        for tier in _DATABASE_STORAGE_TIERS
    }
    prices = _get_prices()
    currency = prices["prices"].get("currency", "EUR")
    items = []
    for zone_prices in prices["prices"]["zone"]:
        region_id = zone_prices["name"]
        for storage in vendor.database_storages:
            storage_id = storage.database_storage_id
            price_key = price_key_by_id.get(storage_id)
            if price_key is None:
                continue
            value = zone_prices.get(price_key)
            if value is None:
                continue
            raw_price = value.get("price") if isinstance(value, dict) else value
            if raw_price is None:
                continue
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region_id,
                    "database_storage_id": storage_id,
                    "unit": PriceUnit.GB_MONTH,
                    # UpCloud list prices are hourly; normalize to GB/month.
                    "price": (float(raw_price) / 100) * _HOURS_PER_MONTH,
                    "currency": currency,
                }
            )
    return items
