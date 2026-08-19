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


@cachier(hash_func=jsoned_hash, separate_files=True)
def _get_device_region_availability(region_id: str, device_type: str = "gpu") -> dict:
    """Return available passthrough devices (GET /1.3/device/availability).

    See https://upcloudltd.github.io/upcloud-openapi-spec/api/device#get-available-passthrough-devices
    """
    params: dict[str, str] = {"type": device_type}
    params["zone"] = region_id
    return _client().api.get_request("/device/availability", params=params)


def _get_gpu_region_availability(region_id: str) -> dict[str, dict]:
    return (
        _get_device_region_availability(region_id)
        .get(region_id, {})
        .get("gpu_plans", {})
    )


UPCLOUD_STORAGES = [
    {
        "id": "hdd",
        "name": "Archive",
        "description": "High-capacity data storage",
        "storage_type": StorageType.HDD,
        "min_size": 1,
        "max_size": 4096,
        "max_iops": 600,
    },
    {
        "id": "standard",
        "name": "Standard",
        "description": "General purpose data storage",
        "storage_type": StorageType.SSD,
        "min_size": 1,
        "max_size": 4096,
        "max_iops": 10000,
    },
    {
        "id": "maxiops",
        "name": "MaxIOPS",
        "description": "High-performance web servers and applications",
        "storage_type": StorageType.SSD,
        "min_size": 1,
        "max_size": 4096,
        "max_iops": 100000,
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
    regions = _client().get_zones()["zones"]["zone"]
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
    servers = _client().get_server_plans()["plans"]["plan"]
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
    prices = _client().get_prices()
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
    prices = _client().get_prices()
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
                "max_throughput": None,
                "min_size": storage["min_size"],
                "max_size": storage["max_size"],
            }
        )
    return items


def inventory_storage_prices(vendor):
    items = []
    prices = _client().get_prices()
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
    prices = _client().get_prices()
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
    prices = _client().get_prices()
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


def inventory_databases(vendor):
    """List UpCloud managed PostgreSQL service plans.

    - Plan ids and topology come from GET /1.3/database/service-types/pg.
    - Supported versions come from the payload `properties.version.enum`.
    - UpCloud Managed Databases are DBaaS clusters, not plain VM images.
    https://developers.upcloud.com/1.3/16-managed-database/
    https://upcloud.com/docs/products/managed-postgresql/configurations/
    """
    payload = _client().api.get_request("/database/service-types/pg")
    plans = payload.get("service_plans", [])
    properties = payload.get("properties", {})
    versions = properties.get("version", {}).get("enum", [])
    server_ids = {server.server_id for server in vendor.servers}

    items = []
    for plan in plans:
        database_id = plan["plan"]
        node_count = plan.get("node_count")
        vcpus = plan.get("core_number")
        memory_amount = plan.get("memory_amount")
        components = plan.get("components", {})
        storage_component = components.get("storage", {})
        # API sizes are MiB (same as memory_amount); schema storage fields use GB.
        storage_size_gb = round(plan["storage_size"] / _MIB_PER_GIB * _GIB_TO_GB)
        storage_step_gb = round(plan["storage_step_size"] / _MIB_PER_GIB * _GIB_TO_GB)
        storage_extra_max_gb = round(
            (plan["storage_cap_size"] - plan["storage_size"])
            / _MIB_PER_GIB
            * _GIB_TO_GB
        )
        dynamic_storage_supported = storage_component.get("dynamic_storage_supported")
        if dynamic_storage_supported:
            storage_extra_min = storage_step_gb
            storage_extra_max = storage_extra_max_gb
        else:
            storage_extra_min = None
            storage_extra_max = None
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
        # Per-node compute profile from service-types/pg `components.compute`.
        server_id = (
            f"{cpu}xCPU-{memory_gb}GB"
            if cpu is not None and memory_gb is not None
            else None
        )
        if server_id not in server_ids:
            server_id = None
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
        # Multi-node plans include primary and standby nodes; standbys accept
        # read-only queries via a separate DNS entry.
        # https://upcloud.com/docs/products/managed-postgresql/high-availability/
        if node_count > 1:
            ha = [DatabaseHaLevel.SINGLE_ZONE]
            ha_strategy = [DatabaseHaStrategy.READABLE_CLUSTER]
        else:
            ha = [DatabaseHaLevel.NONE]
            ha_strategy = [DatabaseHaStrategy.NONE]

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
                "server_id": server_id,
                "engine": DatabaseEngine.POSTGRESQL,
                "wire_protocol": DatabaseWireProtocol.POSTGRESQL,
                "engine_versions": versions,
                # Node topology groups from configurations docs (1/2/3 nodes).
                # https://upcloud.com/docs/products/managed-postgresql/configurations/
                "family": family,
                "vcpus": vcpus,
                "memory_amount": memory_amount,
                "storage_size": storage_size_gb,
                # Extra disk in storage_step_size increments up to cap minus bundled size.
                # https://upcloud.com/docs/changelog/2025-05-26-additional-disk-space-managed-databases/
                "storage_extra_min": storage_extra_min,
                "storage_extra_max": storage_extra_max,
                "storage_extra_autosize": bool(dynamic_storage_supported),
                "ha": ha,
                "ha_strategy": ha_strategy,
                "max_read_replicas": max(node_count - 1, 0),
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
                # Plans include daily full backups (`backup_config.interval`).
                # https://upcloud.com/docs/products/managed-postgresql/backups/
                "scheduled_backups": bool(backup_cfg.get("interval")),
                # PITR retention days from backup_config_pg interval × max_count.
                # https://upcloud.com/docs/products/managed-postgresql/backups/
                "continuous_backups": continuous_backups,
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
                # Plans list orderable zones under `zones.zone`.
                "status": status,
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
        )
    return items


def inventory_database_prices(vendor):
    items = []
    prices = _client().get_prices()
    databases = {database.database_id: database for database in vendor.databases}
    prefix = "managed_database_"
    currency = prices["prices"].get("currency", "EUR")
    for zone_prices in prices["prices"]["zone"]:
        region_id = zone_prices["name"]
        for k, v in zone_prices.items():
            if not k.startswith(prefix):
                continue
            database_id = k[len(prefix) :]
            database = databases.get(database_id)
            if database is None:
                continue
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region_id,
                    "database_id": database_id,
                    "allocation": Allocation.ONDEMAND,
                    "ha": database.ha[0],
                    "ha_strategy": database.ha_strategy[0],
                    "unit": PriceUnit.HOUR,
                    "price": v["price"] / 100,
                    "currency": currency,
                }
            )
    return items


def inventory_database_storages(vendor):
    """List additional managed PostgreSQL disk as a single storage product.

    Extra disk is billed uniformly (`managed_database_tiered_storage_standard`) and
    sold in 10 GiB steps up to 4x each plan's bundled storage.
    https://upcloud.com/docs/changelog/2025-05-26-additional-disk-space-managed-databases/
    https://developers.upcloud.com/1.3/16-managed-database/
    """
    payload = _client().api.get_request("/database/service-types/pg")
    plans = payload.get("service_plans", [])
    if not plans:
        return []
    max_extra_gb = max(
        round((p["storage_cap_size"] - p["storage_size"]) / _MIB_PER_GIB * _GIB_TO_GB)
        for p in plans
    )
    if max_extra_gb <= 0:
        return []
    step_size_gb = round(plans[0]["storage_step_size"] / _MIB_PER_GIB * _GIB_TO_GB)
    # MaxIOPS read/write limits for managed PostgreSQL storage.
    # https://upcloud.com/docs/products/block-storage/tiers/
    # https://upcloud.com/global/blog/flexible-scaling-affordable-zero-hidden-fees-updated-managed-database-plans/
    return [
        {
            "vendor_id": vendor.vendor_id,
            "database_storage_id": "additional-disk",
            "name": "Additional disk",
            "description": (
                "Additional managed PostgreSQL disk in "
                f"{step_size_gb} GB increments up to 4x bundled storage"
            ),
            "scope": DatabaseStorageScope.DATA,
            "min_size": 0,
            "max_size": max_extra_gb,
            "max_iops": 100000,
            "max_throughput": None,
        }
    ]


def inventory_database_storage_prices(vendor):
    """List additional PostgreSQL disk prices from the UpCloud zone price list."""
    if not vendor.database_storages:
        return []
    storage_id = vendor.database_storages[0].database_storage_id
    prices = _client().get_prices()
    currency = prices["prices"].get("currency", "EUR")
    items = []
    for zone_prices in prices["prices"]["zone"]:
        region_id = zone_prices["name"]
        value = zone_prices.get("managed_database_tiered_storage_standard")
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
