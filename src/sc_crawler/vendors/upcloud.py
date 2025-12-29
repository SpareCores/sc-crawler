from functools import cache
from os import environ
from re import compile as recompile

from upcloud_api import CloudManager

from ..lookup import map_compliance_frameworks_to_vendor
from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    PriceUnit,
    StorageType,
    TrafficDirection,
)

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
        # optional leading ALLCAPS chars are the family name
        r"((?P<family>[A-Z]*)-)?" r"(?P<vcpus>[0-9]+)xCPU-" r"(?P<memory>[0-9]+)GB"
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
    }
    data["family"] = family_mapping.get(data["family"], data["family"])
    data["description"] = (
        f"{data['family']} ({data['vcpus']} vCPUs, {data['memory']} GiB RAM)"
    )
    return data


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
    servers = _client().get_server_plans()["plans"]["plan"]
    items = []
    for server in servers:
        server_data = _parse_server_name(server["name"])
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
                "cpu_l1_cache": None,
                "cpu_l2_cache": None,
                "cpu_l3_cache": None,
                "cpu_flags": [],
                "cpus": [],
                "memory_amount": server["memory_amount"],
                "memory_generation": None,
                "memory_speed": None,
                "memory_ecc": None,
                # no GPU options
                "gpu_count": 0,
                "gpu_memory_min": None,
                "gpu_memory_total": None,
                "gpu_manufacturer": None,
                "gpu_family": None,
                "gpu_model": None,
                "gpus": [],
                "storage_size": server["storage_size"],
                "storage_type": (StorageType.SSD if server["storage_tier"] else None),
                "storages": [],
                "network_speed": None,
                "inbound_traffic": 0,
                "outbound_traffic": server["public_traffic_out"],
                "ipv4": 0 if server_data["family"] == "CLOUDNATIVE" else 1,
            }
        )
    return items


def inventory_server_prices(vendor):
    items = []
    prices = _client().get_prices()
    for zone_prices in prices["prices"]["zone"]:
        for k, v in zone_prices.items():
            if not k.startswith("server_plan"):
                continue
            server_plan = k[len("server_plan_") :]
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": zone_prices["name"],
                    "zone_id": zone_prices["name"],
                    "server_id": server_plan,
                    "operating_system": "Linux",
                    "allocation": Allocation.ONDEMAND,
                    "unit": PriceUnit.HOUR,
                    "price": v["price"] / 100,
                    "price_upfront": 0,
                    "price_tiered": [],
                    "currency": "EUR",
                }
            )
    return items


def inventory_server_prices_spot(vendor):
    return []


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
