from concurrent.futures import ThreadPoolExecutor
from functools import cache
from itertools import chain, repeat
from logging import DEBUG
from re import compile as recompile
from re import match, sub
from typing import List

from cachier import cachier
from google.auth import default
from google.cloud import billing_v1, compute_v1
from googleapiclient.discovery import build

from ..lookup import map_compliance_frameworks_to_vendor
from ..sentry import sentry_capture_or_raise
from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    DatabaseEngine,
    DatabaseStorageScope,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)
from ..tables import (
    Vendor,
    Zone,
)
from ..utils import nesteddefaultdict, scmodels_to_dict
from ..vendor_helpers import (
    add_vendor_id,
    merge_database_catalog_rows,
    parallel_fetch_servers,
    preprocess_servers,
)

# ##############################################################################
# Cached gcp client wrappers


@cache
def _project_id() -> str:
    """Returns the project id for the current user as per Application Default Credentials."""
    return default()[1]


def _paginate_list(client, zone=None):
    if zone:
        pager = client.list(project=_project_id(), zone=zone)
    else:
        pager = client.list(project=_project_id())
    items = []
    for page in pager.pages:
        for item in page.items:
            items.append(item)
    return items


@cachier()
def _regions() -> List[compute_v1.types.compute.Region]:
    return _paginate_list(compute_v1.RegionsClient())


@cachier()
def _zones() -> List[compute_v1.types.compute.Zone]:
    return _paginate_list(compute_v1.ZonesClient())


@cachier(separate_files=True)
def _servers(zone: str) -> List[compute_v1.types.compute.MachineType]:
    return _paginate_list(compute_v1.services.machine_types.MachineTypesClient(), zone)


@cache
def _servers_in_zone(zone: str) -> List[str]:
    """Return a list of server names available in a Zone."""
    return [server.name for server in _servers(zone)]


def _server_in_zone(server: str, zone: str) -> bool:
    """Checks if a server (referred by its name) is available in a Zone."""
    return server in _servers_in_zone(zone)


@cachier(separate_files=True)
def _storages(zone: str) -> List[compute_v1.types.compute.DiskType]:
    return _paginate_list(compute_v1.services.disk_types.DiskTypesClient(), zone)


@cache
def _service_name_to_id(service_name: str) -> str:
    """Look up programmatic id to be used in _skus based on human-friendly service name.

    Examples:
        >>> _service_name_to_id("Compute Engine")  # doctest: +SKIP
        'services/6F81-5844-456A'
    """
    client = billing_v1.CloudCatalogClient()
    pager = client.list_services()
    for page in pager.pages:
        for service in page.services:
            if service.display_name == service_name:
                return service.name


@cachier(separate_files=True)
def _skus(service_name: str) -> List[compute_v1.types.compute.Zone]:
    """List all products under a GCP Service.

    Args:
        service_name: Human-friendly service name, e.g. "Compute Engine".
    """
    client = billing_v1.CloudCatalogClient()
    pager = client.list_skus(parent=_service_name_to_id(service_name))
    items = []
    for page in pager.pages:
        for sku in page.skus:
            items.append(sku)
    return items


# ##############################################################################
# Internal helpers

SERVER_FAMILIES = {
    "a2",
    "a3",
    "c2",  # compute optimized
    "c2d",
    "c3",
    "c3d",
    "c4",
    "e2",
    "f1",  # micro instance running on N1
    "g1",  # micro instance running on N1
    "g2",
    "h3",
    "m1",  # memory optimized
    "m2",  # memory optimized + premium
    "m3",
    "n1",
    "n2",
    "n2d",
    "n4",
    "t2a",
    "t2d",
    "z3",
}

# there are a few odd descriptions that needs lookup,
# otherwise the descriptions match the server family
SERVER_DESCRIPTION_TO_FAMILY = {
    "Compute optimized": "C2",
    "Memory-optimized": "M1",
    "Memory Optimized Upgrade Premium for Memory-optimized": "M2",
    "M3 Memory-optimized": "M3",
}

STORAGE_DESCRIPTION_TO_FAMILY = {
    "Storage PD Capacity": "pd-standard",
    "SSD backed PD Capacity": "pd-ssd",
    "SSD backed Local Storage": "local-ssd",
    "Balanced PD Capacity": "pd-balanced",
    "Extreme PD Capacity": "pd-extreme",
    "Hyperdisk Extreme Capacity": "hyperdisk-extreme",
    "Hyperdisk Throughput Capacity": "hyperdisk-throughput",
    "Hyperdisk Balanced Capacity": "hyperdisk-balanced",
}

# partial list of storages to exclude options with extra pricing on IOPS/throughput
STORAGE_ALLOWLIST = ["pd-standard", "pd-ssd", "pd-balanced"]


def _server_family(server_name: str) -> str:
    """Look up server family based on server name"""
    # example server names: f1-micro, n2d-standard-96
    prefix = server_name.lower().split("-")[0]
    if prefix in SERVER_FAMILIES:
        return prefix
    raise KeyError(f"Not known server family for {server_name}")


@cache
def _skus_dict():
    """Look up all Compute Engine SKUs and return in a lookup dict."""
    skus = _skus("Compute Engine")
    lookup = nesteddefaultdict()
    for sku in skus:
        # skip not processed items early
        if sku.category.resource_family not in ["Compute", "Storage"]:
            continue
        if sku.category.resource_family == "Compute":
            if sku.category.usage_type not in ["OnDemand", "Preemptible"]:
                continue
        if sku.category.resource_family == "Storage":
            if sku.category.usage_type != "OnDemand":
                continue
            if sku.category.resource_group not in ["HDD", "SSD", "HDBSP", "HDTSP"]:
                continue

        # helper variables
        regions = sku.service_regions
        if sku.category.usage_type == "OnDemand":
            allocation = "ondemand"
        else:
            allocation = "spot"
        price_tiers = sku.pricing_info[0].pricing_expression.tiered_rates
        assert len(price_tiers) == 1
        price = price_tiers[0].unit_price.nanos / 1e9
        currency = price_tiers[0].unit_price.currency_code

        if sku.category.resource_family == "Compute":
            # servers with pricing as-is
            if sku.category.resource_group in ["F1Micro", "G1Small"]:
                name = sku.category.resource_group[:2].lower()
                for region in regions:
                    lookup["instance"][name][region][allocation] = (price, currency)
                continue

            # servers with CPU + RAM pricing
            if (
                sku.category.resource_group
                in [
                    "CPU",
                    "RAM",
                    # this resource group is also using cpu/ram SKUs,
                    # but can only differentiate by the description
                    "N1Standard",
                ]
                and "Custom" not in sku.description
                and "Sole Tenancy" not in sku.description
                and (
                    "Instance Core running in" in sku.description
                    or "Instance Ram running in" in sku.description
                )
            ):
                # sku.description examples:
                # - A2 Instance Ram running in Finland
                # - Spot Preemptible C3 Instance Core running in Toronto
                # - N2D AMD Instance Ram running in Virginia
                # - M3 Memory-optimized Instance Core running in Warsaw
                # - Spot Preemptible T2A Arm Instance Ram running in Netherlands
                # - N1 Predefined Instance Ram running in EMEA
                family = sub(r"^Spot Preemptible ", "", sku.description)
                family = sub(r" Instance.*", "", family)
                family = sub(r" Predefined$", "", family)
                family = sub(r" AMD$", "", family)
                family = sub(r" Arm$", "", family)

                resource = sku.category.resource_group.lower()
                if sku.category.resource_group == "N1Standard":
                    resource = "ram" if "Instance Ram" in sku.description else "cpu"

                # extract instance family from description (?!)
                family = SERVER_DESCRIPTION_TO_FAMILY.get(family, family).lower()

                for region in regions:
                    lookup[resource][family][region][allocation] = (price, currency)
                continue

        if sku.category.resource_family == "Storage":
            for k, v in STORAGE_DESCRIPTION_TO_FAMILY.items():
                if k in sku.description:
                    storage_name = v
                    break
            else:
                continue
            for region in regions:
                lookup["storage"][storage_name][region]["ondemand"] = (price, currency)
            continue

    # m2 prices are actually premium on the top of m1
    for region in lookup["ram"]["m2"].keys():
        for allocation in lookup["ram"]["m2"][region].keys():
            for what in ["cpu", "ram"]:
                lookup[what]["m2"][region][allocation] = (
                    (
                        lookup[what]["m1"][region][allocation][0]
                        + lookup[what]["m2"][region][allocation][0]
                    ),
                    lookup[what]["m2"][region][allocation][1],
                )

    return lookup


def _search_servers(zone_name: str) -> List[dict]:
    zone_servers = []
    for server in _servers(zone_name):
        zone_servers.append(
            {
                "server_id": str(server.id),
                "name": server.name,
                "api_reference": server.name,
                "display_name": server.name,
                "description": server.description,
                "family": server.name.split("-")[0],
                "vcpus": server.guest_cpus,
                "hypervisor": None,
                "cpu_allocation": (
                    CpuAllocation.SHARED
                    if server.is_shared_cpu
                    else CpuAllocation.DEDICATED
                ),
                "cpu_cores": None,
                "cpu_speed": None,
                "cpu_architecture": (
                    CpuArchitecture.ARM64
                    if server.name.startswith("t2a")
                    else CpuArchitecture.X86_64
                ),
                "cpu_manufacturer": None,
                "cpu_family": None,
                "cpu_model": None,
                "cpus": [],
                "memory_amount": server.memory_mb,
                "gpu_count": (
                    server.accelerators[0].guest_accelerator_count
                    if server.accelerators
                    else 0
                ),
                "gpu_memory_min": 0 if not server.accelerators else None,
                "gpu_memory_total": 0 if not server.accelerators else None,
                "gpu_manufacturer": None,
                "gpu_model": (
                    server.accelerators[0].guest_accelerator_type
                    if server.accelerators
                    else None
                ),
                "gpus": [],
                # TODO no API to get local disks for an instance type
                "storage_size": 0,
                "storage_type": None,
                "storages": [],
                # TODO: have to implement manual mapping for network_speed related fields
                "network_speed_baseline": None,
                "network_speed_max": None,
                "network_storage_speed_baseline": None,
                "network_storage_speed_max": None,
                "inbound_traffic": 0,
                "outbound_traffic": 0,
                "ipv4": 0,
                "status": (
                    Status.ACTIVE if server.deprecated.state == "" else Status.INACTIVE
                ),
            }
        )
    return zone_servers


def _inventory_server_prices(vendor: Vendor, allocation: Allocation) -> List[dict]:
    regions = scmodels_to_dict(vendor.regions, keys=["name"])
    skus = _skus_dict()
    items = []

    for server in vendor.servers:
        try:
            family = _server_family(server.name)
        except KeyError as e:
            vendor.log(f"Skip instance: {str(e)}", DEBUG)
            continue

        # https://cloud.google.com/compute/docs/memory-optimized-machines#m1_series
        # N1 -> M1 rename "to more clearly identify the machines"
        if match("n1-(mega|ultra)mem-[0-9]{2}", server.name):
            family = "m1"

        # price per instance or cpu/ram
        server_regions = [*skus["instance"][family].keys(), *skus["cpu"][family].keys()]
        assert len(server_regions) > 0

        for server_region in server_regions:
            # skip edge regions
            region = regions.get(server_region)
            if region is None:
                vendor.log(
                    f"Skip unknown '{server_region}' region for {server.name}",
                    DEBUG,
                )
                continue

            # try instance-level pricing
            if skus["instance"][family]:
                try:
                    price, currency = skus["instance"][family][server_region][
                        allocation.value.lower()
                    ]
                except ValueError:
                    vendor.log(
                        f"{allocation.value} price not found for '{server.name}' in '{server_region}'",
                        DEBUG,
                    )
                    continue
            # add ram and cpu prices
            elif skus["cpu"][family]:
                try:
                    price = (
                        skus["cpu"][family][server_region][allocation.value.lower()][0]
                        * server.vcpus
                        + skus["ram"][family][server_region][allocation.value.lower()][
                            0
                        ]
                        * server.memory_amount
                        / 1024
                    )
                    currency = skus["cpu"][family][server_region][
                        allocation.value.lower()
                    ][1]
                except (ValueError, TypeError):
                    vendor.log(
                        f"{allocation.value} price not found for '{server.name}' in '{server_region}'",
                        DEBUG,
                    )
                    continue
            else:
                raise KeyError(f"SKU not found for {server.name}")

            for zone in region.zones:
                # server might not be actually available in the the region
                if _server_in_zone(server.name, zone.name):
                    items.append(
                        {
                            "vendor_id": vendor.vendor_id,
                            "region_id": region.region_id,
                            "zone_id": zone.zone_id,
                            "server_id": server.server_id,
                            "operating_system": "Linux",
                            "allocation": allocation,
                            "unit": PriceUnit.HOUR,
                            "price": price,
                            "price_upfront": 0,
                            "price_tiered": [],
                            "currency": currency,
                        }
                    )

    return items


# ##############################################################################
# Public methods to fetch data


def inventory_compliance_frameworks(vendor):
    """Manual list of compliance frameworks known for GCP.

    Resources: <https://cloud.google.com/compliance?hl=en>"""
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id, ["hipaa", "soc2t2", "iso27001"]
    )


def inventory_regions(vendor):
    """List all available GCP regions via API calls.

    Some data sources are not available from APIs, and were collected manually:

    - location: <https://cloud.google.com/compute/docs/regions-zones#available> and <https://en.wikipedia.org/wiki/Google_data_centers>,
    - lon/lat coordinates: <https://en.wikipedia.org/wiki/Google_data_centers#Locations> and approximation based on the city when no more accurate data was available.
    - energy carbon data: <https://cloud.google.com/sustainability/region-carbon#data> and <https://github.com/GoogleCloudPlatform/region-carbon-info>,
    - launch dates were collected from [Wikipedia](https://en.wikipedia.org/wiki/Google_Cloud_Platform#Regions_and_zones) and GCP blog posts, such as <https://medium.com/@retomeier/an-annotated-history-of-googles-cloud-platform-90b90f948920> and <https://cloud.google.com/blog/products/infrastructure/introducing-new-google-cloud-regions>.

    Note that many GCP regions use more than 90% green energy,
    but the related flag in our database is set to `False` as not being 100%.
    """

    manual_data = {
        "africa-south1": {
            "country_id": "ZA",
            "city": "Johannesburg",
            # https://cloud.google.com/blog/products/infrastructure/heita-south-africa-new-cloud-region
            "founding_year": 2024,
            "green_energy": False,
            # approximation based on city
            "lat": -26.0420631,
            "lon": 28.0589808,
        },
        "asia-east1": {
            "country_id": "TW",
            "state": "Changhua County",
            "founding_year": 2013,
            "green_energy": False,
            "lat": 24.1385,
            "lon": 120.425722,
        },
        "asia-east2": {
            "country_id": "HK",
            # https://cloud.google.com/blog/products/gcp/gcps-region-in-hong-kong-is-now-open
            "founding_year": 2018,
            "green_energy": False,
            # approximation based on country
            "lat": 22.2772377,
            "lon": 114.1703066,
            "display_name": "Hong Kong",
        },
        "asia-northeast1": {
            "country_id": "JP",
            "city": "Tokyo",
            "state": "Japan",
            "founding_year": 2016,
            "green_energy": False,
            # approximation based on city
            "lat": 35.6433846,
            "lon": 139.7684933,
        },
        "asia-northeast2": {
            "country_id": "JP",
            "city": "Osaka",
            "founding_year": 2019,
            "green_energy": False,
            # approximation based on city
            "lat": 34.6696646,
            "lon": 135.4846612,
        },
        "asia-northeast3": {
            "country_id": "KR",
            "city": "Seoul",
            "founding_year": 2020,
            "green_energy": False,
            # approximation based on city
            "lat": 37.5514982,
            "lon": 126.97784,
        },
        "asia-south1": {
            "country_id": "IN",
            "city": "Mumbai",
            "founding_year": 2017,
            "green_energy": False,
            # approximation based on city
            "lat": 19.0709441,
            "lon": 72.8726468,
        },
        "asia-south2": {
            "country_id": "IN",
            "city": "Delhi",
            "founding_year": 2021,
            "green_energy": False,
            # approximation based on city
            "lat": 28.6439839,
            "lon": 76.9284239,
        },
        "asia-southeast1": {
            "country_id": "SG",
            "city": "Jurong West",
            "founding_year": 2017,
            "green_energy": False,
            "lat": 1.351333,
            "lon": 103.709778,
        },
        "asia-southeast2": {
            "country_id": "ID",
            "city": "Jakarta",
            "founding_year": 2020,
            "green_energy": False,
            # approximation based on city
            "lat": -6.2297401,
            "lon": 106.747117,
        },
        "asia-southeast3": {
            "country_id": "TH",
            "city": "Bangkok",
            "founding_year": 2025,
            "green_energy": False,
            # approximation based on city
            "lat": 15.870032,
            "lon": 100.992538,
        },
        "australia-southeast1": {
            "country_id": "AU",
            "city": "Sydney",
            "founding_year": 2017,
            "green_energy": False,
            # approximation based on city
            "lat": -33.8375583,
            "lon": 150.9488095,
        },
        "australia-southeast2": {
            "country_id": "AU",
            "city": "Melbourne",
            "founding_year": 2021,
            "green_energy": False,
            # approximation based on city
            "lat": -37.8038607,
            "lon": 144.7119569,
        },
        "europe-central2": {
            "country_id": "PL",
            "city": "Warsaw",
            "founding_year": 2021,
            "green_energy": False,
            # approximation based on city
            "lat": 52.2328871,
            "lon": 20.8966164,
        },
        "europe-north1": {
            "country_id": "FI",
            "city": "Hamina",
            "founding_year": 2018,
            "green_energy": False,
            "lat": 60.536578,
            "lon": 27.117003,
        },
        "europe-north2": {
            "country_id": "SE",
            "city": "Stockholm",
            "founding_year": 2025,
            "green_energy": False,
            # approximation based on city
            "lat": 59.334591,
            "lon": 18.06324,
        },
        "europe-southwest1": {
            "country_id": "ES",
            "city": "Madrid",
            "founding_year": 2022,
            "green_energy": False,
            "lat": 40.519533,
            "lon": -3.340937,
        },
        "europe-west1": {
            "country_id": "BE",
            "city": "St. Ghislain",
            # https://medium.com/@retomeier/an-annotated-history-of-googles-cloud-platform-90b90f948920
            "founding_year": 2015,
            "green_energy": False,
            "lat": 50.469333,
            "lon": 3.865472,
        },
        "europe-west10": {
            "country_id": "DE",
            "city": "Berlin",
            "founding_year": 2023,
            "green_energy": False,
            # approximation based on city
            "lat": 52.5105672,
            "lon": 13.3806972,
        },
        "europe-west12": {
            "country_id": "IT",
            "city": "Turin",
            "founding_year": 2023,
            "green_energy": False,
            "lat": 45.146729,
            "lon": 7.742147,
        },
        "europe-west2": {
            "country_id": "GB",
            "city": "London",
            "founding_year": 2017,
            "green_energy": False,
            # approximation based on city
            "lat": 51.5090133,
            "lon": -0.2118157,
        },
        "europe-west3": {
            "country_id": "DE",
            "city": "Frankfurt",
            "founding_year": 2017,
            "green_energy": False,
            "lat": 50.12263,
            "lon": 8.974168,
        },
        "europe-west4": {
            "country_id": "NL",
            "city": "Eemshaven",
            "founding_year": 2018,
            "green_energy": False,
            "lat": 52.790105,
            "lon": 5.029219,
        },
        "europe-west6": {
            "country_id": "CH",
            "city": "Zurich",
            "founding_year": 2019,
            "green_energy": False,
            "lat": 47.445926,
            "lon": 8.210909,
        },
        "europe-west8": {
            "country_id": "IT",
            "city": "Milan",
            "founding_year": 2022,
            "green_energy": False,
            # approximation based on city
            "lat": 45.4615551,
            "lon": 9.1389572,
        },
        "europe-west9": {
            "country_id": "FR",
            "city": "Paris",
            "founding_year": 2022,
            "green_energy": False,
            # approximation based on city
            "lat": 48.8641797,
            "lon": 2.3109137,
        },
        "me-central1": {
            "country_id": "QA",
            "city": "Doha",
            "founding_year": 2023,
            "green_energy": False,
            # approximation based on city
            "lat": 25.272868,
            "lon": 51.4717522,
        },
        "me-central2": {
            "country_id": "SA",
            "city": "Dammam",
            "founding_year": 2023,
            "green_energy": False,
            # approximation based on city
            "lat": 26.3826288,
            "lon": 49.9675732,
        },
        "me-west1": {
            "country_id": "IL",
            "city": "Tel Aviv",
            "founding_year": 2022,
            "green_energy": False,
            # approximation based on city
            "lat": 32.0491183,
            "lon": 34.7891105,
        },
        "northamerica-northeast1": {
            "country_id": "CA",
            "city": "Montréal",
            "founding_year": 2018,
            "green_energy": True,
            # approximation based on city
            "lat": 45.4933996,
            "lon": -73.728239,
        },
        "northamerica-northeast2": {
            "country_id": "CA",
            "city": "Toronto",
            "founding_year": 2021,
            "green_energy": False,
            # approximation based on city
            "lat": 43.72666,
            "lon": -79.5355309,
        },
        "southamerica-east1": {
            "country_id": "BR",
            "city": "Osasco",
            "state": "São Paulo",
            "founding_year": 2017,
            "green_energy": False,
            # approximation based on city
            "lat": -23.5267431,
            "lon": -46.8096539,
        },
        "southamerica-west1": {
            "country_id": "CL",
            "city": "Santiago",
            "founding_year": 2021,
            "green_energy": False,
            "lat": -33.520515,
            "lon": -70.721695,
        },
        # NOTE this is not announced yet, but showing up in API from time to time
        "northamerica-south1": {
            # https://mexicobusiness.news/cloudanddata/news/google-cloud-announces-first-mexican-data-region-queretaro
            "country_id": "MX",
            "city": "Queretaro",
            "founding_year": 2025,
            "green_energy": False,
            # approximation based on city
            "lat": 20.5896,
            "lon": -100.3897,
        },
        "us-central1": {
            "country_id": "US",
            "city": "Council Bluffs",
            "state": "Iowa",
            "founding_year": 2009,
            "green_energy": False,
            "lat": 41.168253,
            "lon": -95.796125,
        },
        "us-east1": {
            "country_id": "US",
            "city": "Moncks Corner",
            "state": "South Carolina",
            "founding_year": 2015,
            "green_energy": False,
            "lat": 33.064111,
            "lon": -80.043361,
        },
        "us-east4": {
            "country_id": "US",
            "city": "Ashburn",
            "state": "Virginia",
            "founding_year": 2017,
            "green_energy": False,
            "lat": 38.943331,
            "lon": -77.524336,
        },
        "us-east5": {
            "country_id": "US",
            "city": "Columbus",
            "state": "Ohio",
            "founding_year": 2022,
            "green_energy": False,
            # approximation based on city
            "lat": 39.9773124,
            "lon": -83.0423282,
        },
        "us-south1": {
            "country_id": "US",
            "city": "Dallas",
            "state": "Texas",
            "founding_year": 2022,
            "green_energy": False,
            "lat": 32.44317,
            "lon": -97.062324,
        },
        "us-west1": {
            "country_id": "US",
            "city": "The Dalles",
            "state": "Oregon",
            "founding_year": 2016,
            "green_energy": False,
            "lat": 45.632511,
            "lon": -121.202267,
        },
        "us-west2": {
            "country_id": "US",
            "city": "Los Angeles",
            "state": "California",
            "founding_year": 2018,
            "green_energy": False,
            # approximation based on city
            "lat": 34.0549694,
            "lon": -118.3753618,
        },
        "us-west3": {
            "country_id": "US",
            "city": "Salt Lake City",
            "state": "Utah",
            "founding_year": 2020,
            "green_energy": False,
            # approximation based on city
            "lat": 40.7386099,
            "lon": -111.9609998,
        },
        "us-west4": {
            "country_id": "US",
            "city": "Las Vegas",
            "state": "Nevada",
            "founding_year": 2020,
            "green_energy": False,
            "lat": 36.055625,
            "lon": -115.010226,
        },
    }

    # add API reference and display names
    for k, v in manual_data.items():
        v["api_reference"] = k
        if v.get("display_name") is None:
            v["display_name"] = v.get("city", v.get("state", ""))
            if v.get("display_name"):
                v["display_name"] = v["display_name"] + " (" + v["country_id"] + ")"
            else:
                v["display_name"] = v["country_id"]

    regions = _regions()
    items = []
    for region in regions:
        with sentry_capture_or_raise(vendor=vendor):
            if region.name not in manual_data:
                raise KeyError(f"Unknown region metadata for {region.name}")
            item = {
                "vendor_id": vendor.vendor_id,
                "region_id": str(region.id),
                "name": region.name,
            }
            for k, v in manual_data[region.name].items():
                item[k] = v
            items.append(item)
    return items


def inventory_zones(vendor):
    """List all available GCP zones via API calls."""
    items = []
    regions = scmodels_to_dict(vendor.regions, keys=["name"])
    for zone in _zones():
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                # example `zone.region`:
                # https://www.googleapis.com/compute/v1/projects/algebraic-pier-412621/regions/us-east4
                "region_id": regions[zone.region.split("/")[-1]].region_id,
                "zone_id": str(zone.id),
                "name": zone.name,
                "api_reference": zone.name,
                "display_name": zone.name,
            }
        )
    return items


def inventory_servers(vendor):
    """List all available GCP servers available in all zones."""
    servers = parallel_fetch_servers(vendor, _search_servers, "name", "zones")
    servers = preprocess_servers(servers, vendor, add_vendor_id)
    return servers


def inventory_server_prices(vendor):
    """List all available GCP server ondemand prices in all regions."""
    return _inventory_server_prices(vendor, Allocation.ONDEMAND)


def inventory_server_prices_spot(vendor):
    """List all available GCP server spot prices in all regions."""
    return _inventory_server_prices(vendor, Allocation.SPOT)


def inventory_storages(vendor):
    """List all available GCP disk storage options available in all zones.

    For more details on the disk types, check <https://cloud.google.com/compute/docs/disks#disk-types>."""
    vendor.progress_tracker.start_task(
        name="Scanning zone(s) for storage(s)", total=len(vendor.zones)
    )

    def search_storages(zone: Zone, vendor: Vendor) -> List[dict]:
        zone_storages = []
        for storage in _storages(zone.name):
            valid_sizes = storage.valid_disk_size.replace("GB", "").split("-")
            zone_storages.append(
                {
                    "storage_id": str(storage.id),
                    "vendor_id": vendor.vendor_id,
                    "name": storage.name,
                    "description": storage.description,
                    "storage_type": (
                        StorageType.SSD
                        if storage.name != "pd-standard"
                        else StorageType.HDD
                    ),
                    "max_iops": None,
                    "max_throughput": None,
                    "min_size": int(valid_sizes[0]),
                    "max_size": int(valid_sizes[1]),
                }
            )
        vendor.log(f"{len(zone_storages)} storage(s) found in {zone.name}.")
        vendor.progress_tracker.advance_task()
        return zone_storages

    with ThreadPoolExecutor(max_workers=8) as executor:
        storages = executor.map(search_storages, vendor.zones, repeat(vendor))
    storages = list(chain.from_iterable(storages))

    vendor.log(f"{len(storages)} storage(s) found in {len(vendor.zones)} zones.")
    storages = list({p["name"]: p for p in storages}.values())
    vendor.log(f"{len(storages)} unique storage(s) found.")
    storages = [s for s in storages if s["name"] in STORAGE_ALLOWLIST]
    vendor.log(f"{len(storages)} storage(s) after dropping items with complex pricing.")
    vendor.progress_tracker.hide_task()
    return storages


def inventory_storage_prices(vendor):
    """List all available GCP disk storage prices in all regions."""
    regions = scmodels_to_dict(vendor.regions, keys=["name"])
    skus = _skus_dict()
    items = []
    for storage in vendor.storages:
        storage_regions = skus["storage"][storage.name].keys()
        for storage_region in storage_regions:
            # skip edge regions
            region = regions.get(storage_region)
            if region is None:
                vendor.log(
                    f"Skip unknown '{storage_region}' region for {storage.name}",
                    DEBUG,
                )
                continue

            price, currency = skus["storage"][storage.name][storage_region]["ondemand"]
            for zone in region.zones:
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": region.region_id,
                        "storage_id": storage.storage_id,
                        "unit": PriceUnit.GB_MONTH,
                        "price": float(price),
                        "currency": currency,
                    }
                )
    return items


def inventory_traffic_prices(vendor):
    """List inbound and outbound network traffic prices in all GCP regions."""
    regions = scmodels_to_dict(vendor.regions, keys=["name"])
    skus = _skus("Compute Engine")
    items = []
    for sku in skus:
        # skip not processed items early
        if sku.category.resource_family != "Network":
            continue
        if sku.category.resource_group not in [
            "StandardInternetEgress",
            "StandardInternetIngress",
        ]:
            continue

        # helper variables
        traffic_regions = sku.service_regions
        tiered_rates = sku.pricing_info[0].pricing_expression.tiered_rates
        price_tiers = []
        for i in range(len(tiered_rates)):
            price_tiers.append(
                {
                    "lower": tiered_rates[i].start_usage_amount,
                    "upper": "Infinity"
                    if i == len(tiered_rates) - 1
                    else tiered_rates[i + 1].start_usage_amount,
                    "price": tiered_rates[i].unit_price.nanos / 1e9,
                }
            )

        for traffic_region in traffic_regions:
            region = regions.get(traffic_region)
            if region is None:
                vendor.log(
                    f"Skip unknown '{traffic_region}' region for {sku.description}",
                    DEBUG,
                )
                continue
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "price": max([float(t["price"]) for t in price_tiers]),
                    "price_tiered": price_tiers,
                    "currency": tiered_rates[0].unit_price.currency_code,
                    "unit": PriceUnit.GB_MONTH,
                    "direction": (
                        TrafficDirection.OUT
                        if sku.category.resource_group == "StandardInternetEgress"
                        else TrafficDirection.IN
                    ),
                }
            )

    return items


def inventory_ipv4_prices(vendor):
    """List the price of an attached IPv4 address in all GCP regions.

    Note that this data was not found using the APIs (only unattached static IPs),
    so the values are recorded manually from <https://cloud.google.com/vpc/network-pricing#ipaddress>.
    """
    # skus = _skus("Compute Engine")
    # for sku in skus:
    #     if sku.category.resource_family != "Network":
    #         continue
    #     if sku.description == "Static Ip Charge":
    #         pass
    items = []
    for region in vendor.regions:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "price": 0.005,
                "currency": "USD",
                "unit": PriceUnit.HOUR,
            }
        )
    return items


# PostgreSQL Cloud SQL support
# https://cloud.google.com/sql/docs/postgres/storage-options-overview


@cachier(separate_files=True)
def _sqladmin_service():
    creds, _ = default()
    return build("sqladmin", "v1", credentials=creds, cache_discovery=False)


@cachier(separate_files=True)
def _pg_sqladmin_metadata() -> dict:
    service = _sqladmin_service()
    tiers = service.tiers().list(project=_project_id()).execute().get("items", [])
    flags = service.flags().list().execute().get("items", [])
    engine_versions: set[str] = set()
    custom_config = custom_extensions = False
    for flag in flags:
        name = flag.get("name") or ""
        if name.startswith("cloudsql.enable_"):
            custom_config = True
        if name in _PG_EXTENSION_FLAGS:
            custom_extensions = True
        for version in flag.get("appliesTo", []):
            if isinstance(version, str) and version.startswith("POSTGRES_"):
                engine_versions.add(version.removeprefix("POSTGRES_").replace("_", "."))
    return {
        "tiers": tiers,
        "engine_versions": sorted(
            engine_versions,
            key=lambda value: tuple(int(part) for part in value.split(".")),
        ),
        "custom_config": custom_config or None,
        "custom_extensions": custom_extensions or None,
    }


@cachier(separate_files=True)
def _cloud_sql_skus():
    return _skus("Cloud SQL")


_PG_CUSTOM_TIER_RE = recompile(r"^db-custom-(\d+)-(\d+)$")
_PG_NAMED_TIER_CPU_RE = recompile(r"-(\d+)$")
_PG_N4_TIER_MARKERS = ("c4a", "perf-optimized", "memory-optimized")
_PG_SHARED_TIERS = {"db-f1-micro": "f1-micro", "db-g1-small": "g1-small"}
_PG_STORAGE_METERS = (
    (
        recompile(r": Zonal - Enterprise Storage Hyperdisk Balanced Capacity in "),
        "cloudsql-hyperdisk",
    ),
    (
        recompile(r": Zonal - Enterprise Plus Standard Storage in "),
        "cloudsql-ssd",
    ),
    (recompile(r": Zonal - Standard storage in "), "cloudsql-ssd-standard"),
    (recompile(r": Zonal - Low cost storage in "), "cloudsql-hdd"),
)
_PG_MAX_STORAGE_GB = 65536
_PG_STORAGE_SPECS: dict[str, dict] = {
    "cloudsql-ssd": {
        "name": "Enterprise Plus SSD",
        "description": (
            "Enterprise Plus standard SSD (Persistent Disk) for N2 / Enterprise Plus "
            "machine series; 10-65536 GB, up to 100k IOPS"
        ),
        "min_size": 10,
        "max_size": _PG_MAX_STORAGE_GB,
        "max_iops": 100_000,
        "max_throughput": 1200,
    },
    "cloudsql-ssd-standard": {
        "name": "Enterprise SSD",
        "description": (
            "Standard SSD storage for Enterprise edition (N1, custom, shared-core); "
            "10-65536 GB, up to 100k IOPS"
        ),
        "min_size": 10,
        "max_size": _PG_MAX_STORAGE_GB,
        "max_iops": 100_000,
        "max_throughput": 1200,
    },
    "cloudsql-hdd": {
        "name": "Low-cost HDD",
        "description": (
            "Low cost HDD for general-purpose shared or dedicated core series; "
            "10-65536 GB, up to 15k IOPS"
        ),
        "min_size": 10,
        "max_size": _PG_MAX_STORAGE_GB,
        "max_iops": 15_000,
        "max_throughput": 1200,
    },
    "cloudsql-hyperdisk": {
        "name": "Hyperdisk Balanced",
        "description": (
            "Hyperdisk Balanced capacity for N4 and C4A machine series; "
            "20-65536 GB, up to 160k IOPS"
        ),
        "min_size": 20,
        "max_size": _PG_MAX_STORAGE_GB,
        "max_iops": 160_000,
        "max_throughput": 2400,
    },
}
_PG_SHARED_INSTANCE_RE = recompile(
    r": Zonal - (?:Extended support )?(f1-micro|g1-small)(?: v\d+)? in "
)
_PG_VCPU_RE = recompile(r": Zonal - (?:Extended support )?(?:Enterprise N4 )?vCPU in ")
_PG_RAM_RE = recompile(r": Zonal - (?:Extended support )?(?:Enterprise N4 )?RAM in ")
_PG_EXTENSION_FLAGS = frozenset(
    {
        "cloudsql.enable_pg_cron",
        "cloudsql.enable_anon",
        "cloudsql.enable_pgaudit",
        "cloudsql.enable_pglogical",
    }
)
_PG_TIER_FAMILY_LABELS = {
    "f1-micro": "Shared f1-micro",
    "g1-small": "Shared g1-small",
    "n1-standard": "N1 Standard",
    "n1-highmem": "N1 High Memory",
    "perf-optimized-N": "Performance Optimized N",
    "c4a-highmem": "C4A High Memory",
    "memory-optimized-N": "Memory Optimized N",
    "custom": "Custom",
}


def _sku_unit_price(sku) -> float | None:
    if not sku.pricing_info:
        return None
    tiered = sku.pricing_info[0].pricing_expression.tiered_rates
    if not tiered:
        return None
    unit_price = tiered[0].unit_price
    return unit_price.units + unit_price.nanos / 1e9


def _pg_storage_id(description: str) -> str | None:
    if (
        "for Postgre" not in description
        or "FDC Trial" in description
        or ": Regional -" in description
        or (": Zonal -" not in description and ": Zonal-" not in description)
        or any(token in description for token in ("IOPS", "Throughput", "Cache"))
    ):
        return None
    for pattern, storage_id in _PG_STORAGE_METERS:
        if pattern.search(description):
            return storage_id
    return None


def _pg_billing_catalog() -> tuple[
    dict[tuple[str, str, str], object], frozenset[tuple[str, str]]
]:
    compute_index: dict[tuple[str, str, str], object] = {}
    ha_families: set[tuple[str, str]] = set()
    for sku in _cloud_sql_skus():
        description = sku.description or ""
        if "for Postgre" not in description:
            continue
        if ": Regional -" in description:
            if "vCPU" in description:
                family = (
                    "enterprise_n4" if "Enterprise N4" in description else "enterprise"
                )
                for region in sku.service_regions:
                    if region:
                        ha_families.add((region, family))
            continue
        if ": Zonal -" not in description and ": Zonal-" not in description:
            continue

        sku_class = None
        if match := _PG_SHARED_INSTANCE_RE.search(description):
            sku_class = ("shared", match.group(1))
        else:
            extended = "Extended support" in description
            if _PG_VCPU_RE.search(description):
                family = (
                    "enterprise_n4" if "Enterprise N4" in description else "enterprise"
                )
                if extended and family == "enterprise":
                    sku_class = ("enterprise_extended", "vcpu")
                elif not extended:
                    sku_class = (family, "vcpu")
            elif _PG_RAM_RE.search(description):
                family = (
                    "enterprise_n4" if "Enterprise N4" in description else "enterprise"
                )
                if extended and family == "enterprise":
                    sku_class = ("enterprise_extended", "ram")
                elif not extended:
                    sku_class = (family, "ram")

        if not sku_class:
            continue
        family, component = sku_class
        for region in sku.service_regions:
            if region:
                compute_index.setdefault((region, family, component), sku)
    return compute_index, frozenset(ha_families)


def inventory_databases(vendor):
    vendor.progress_tracker.start_task(name="Fetching PostgreSQL tier(s)", total=None)
    meta = _pg_sqladmin_metadata()
    _, ha_families = _pg_billing_catalog()
    vendor.progress_tracker.hide_task()

    rows = []
    tiers = meta["tiers"]
    vendor.progress_tracker.start_task(name="Processing database(s)", total=len(tiers))
    for tier in tiers:
        tier_name = tier.get("tier")
        if not tier_name:
            vendor.progress_tracker.advance_task()
            continue

        if match := _PG_CUSTOM_TIER_RE.match(tier_name):
            cpu_count = int(match.group(1))
        elif match := _PG_NAMED_TIER_CPU_RE.search(tier_name):
            cpu_count = int(match.group(1))
        else:
            cpu_count = None

        ram_bytes = int(tier.get("RAM") or 0)
        memory_amount = int(ram_bytes / 1_048_576) if ram_bytes else None

        if tier_name.startswith("db-custom-"):
            family_slug = "custom"
        else:
            stripped = tier_name.removeprefix("db-")
            parts = stripped.split("-")
            family_slug = (
                "-".join(parts[:-1]) if parts and parts[-1].isdigit() else stripped
            )

        spec_parts: list[str] = []
        if cpu_count is not None:
            spec_parts.append(f"{cpu_count} vCPU{'s' if cpu_count != 1 else ''}")
        if memory_amount is not None:
            memory_gib = round(memory_amount / 1024, 1)
            gib_label = (
                f"{int(memory_gib)} GB RAM"
                if memory_gib == int(memory_gib)
                else f"{memory_gib:g} GB RAM"
            )
            spec_parts.append(gib_label)
        family_label = _PG_TIER_FAMILY_LABELS.get(
            family_slug, family_slug.replace("-", " ").title()
        )
        description = f"PostgreSQL Cloud SQL {family_label}"
        if spec_parts:
            description = f"{description} ({', '.join(spec_parts)})"

        raw_regions = tier.get("region")
        if isinstance(raw_regions, str):
            tier_regions = [raw_regions]
        elif isinstance(raw_regions, list):
            tier_regions = [region for region in raw_regions if isinstance(region, str)]
        else:
            tier_regions = []

        if tier_name in _PG_SHARED_TIERS:
            price_family = "shared"
        elif any(marker in tier_name.lower() for marker in _PG_N4_TIER_MARKERS):
            price_family = "enterprise_n4"
        else:
            price_family = "enterprise"

        ha_supported = None
        if tier_regions:
            if price_family == "shared":
                ha_supported = False
            else:
                ha_supported = any(
                    (region, price_family) in ha_families
                    or (region, "enterprise") in ha_families
                    or (region, "enterprise_n4") in ha_families
                    for region in tier_regions
                )

        rows.append(
            {
                "vendor_id": vendor.vendor_id,
                "database_id": tier_name,
                "name": tier_name,
                "api_reference": tier_name,
                "display_name": tier_name,
                "description": description,
                "engine": DatabaseEngine.POSTGRESQL,
                "engine_versions": meta["engine_versions"],
                "family": family_slug,
                "vcpus": cpu_count,
                "memory_amount": memory_amount,
                "storage_size": None,
                "ha_supported": ha_supported,
                "storage_autoscaling": None,
                # https://cloud.google.com/sql/docs/postgres/backup-recovery/backups
                "scheduled_backups": True,
                # https://cloud.google.com/sql/docs/postgres/backup-recovery/pitr
                "continuous_backups": None,
                "custom_config": meta["custom_config"],
                "custom_extensions": meta["custom_extensions"],
            }
        )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return merge_database_catalog_rows(rows)


def inventory_database_prices(vendor):
    vendor.progress_tracker.start_task(name="Fetching Cloud SQL SKU(s)", total=None)
    compute_index, _ = _pg_billing_catalog()
    tiers = _pg_sqladmin_metadata()["tiers"]
    vendor.progress_tracker.hide_task()

    items = []
    vendor.progress_tracker.start_task(
        name="Processing database_price(s)", total=len(tiers)
    )
    for tier in tiers:
        tier_name = tier.get("tier")
        if not tier_name:
            vendor.progress_tracker.advance_task()
            continue

        if match := _PG_CUSTOM_TIER_RE.match(tier_name):
            cpu_count = int(match.group(1))
        elif match := _PG_NAMED_TIER_CPU_RE.search(tier_name):
            cpu_count = int(match.group(1))
        else:
            cpu_count = None

        ram_bytes = int(tier.get("RAM") or 0)
        memory_gib = ram_bytes / (1024**3) if ram_bytes else None

        raw_regions = tier.get("region")
        if isinstance(raw_regions, str):
            tier_regions = {raw_regions}
        elif isinstance(raw_regions, list):
            tier_regions = {region for region in raw_regions if isinstance(region, str)}
        else:
            tier_regions = set()

        if tier_name in _PG_SHARED_TIERS:
            price_family = "shared"
        elif any(marker in tier_name.lower() for marker in _PG_N4_TIER_MARKERS):
            price_family = "enterprise_n4"
        else:
            price_family = "enterprise"

        for region in vendor.regions:
            if tier_regions and region.api_reference not in tier_regions:
                continue

            hourly = currency = None
            if price_family == "shared":
                component = _PG_SHARED_TIERS[tier_name]
                instance_sku = compute_index.get(
                    (region.api_reference, "shared", component)
                )
                if instance_sku is not None:
                    hourly = _sku_unit_price(instance_sku)
                    if hourly is not None:
                        tiered = instance_sku.pricing_info[
                            0
                        ].pricing_expression.tiered_rates
                        currency = tiered[0].unit_price.currency_code or "USD"
            elif cpu_count is not None and memory_gib is not None:
                vcpu_sku = compute_index.get(
                    (region.api_reference, price_family, "vcpu")
                )
                ram_sku = compute_index.get((region.api_reference, price_family, "ram"))
                if vcpu_sku is not None and ram_sku is not None:
                    vcpu_hourly = _sku_unit_price(vcpu_sku)
                    ram_hourly = _sku_unit_price(ram_sku)
                    if vcpu_hourly is not None and ram_hourly is not None:
                        hourly = vcpu_hourly * cpu_count + ram_hourly * memory_gib
                        vcpu_tiered = vcpu_sku.pricing_info[
                            0
                        ].pricing_expression.tiered_rates
                        currency = vcpu_tiered[0].unit_price.currency_code or "USD"

            if hourly is None:
                continue
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "database_id": tier_name,
                    "allocation": Allocation.ONDEMAND,
                    "unit": PriceUnit.HOUR,
                    "price": hourly,
                    "price_upfront": 0,
                    "price_tiered": [],
                    "currency": currency or "USD",
                }
            )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return items


def inventory_database_storages(vendor):
    vendor.progress_tracker.start_task(name="Fetching Cloud SQL SKU(s)", total=None)
    found = {
        storage_id
        for sku in _cloud_sql_skus()
        if (storage_id := _pg_storage_id(sku.description or ""))
    }
    vendor.progress_tracker.hide_task()

    items = []
    vendor.progress_tracker.start_task(
        name="Processing database_storage(s)", total=len(found)
    )
    for storage_id in sorted(found):
        spec = _PG_STORAGE_SPECS[storage_id]
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "database_storage_id": storage_id,
                "name": spec["name"],
                "description": spec["description"],
                "scope": DatabaseStorageScope.DATA,
                "min_size": spec["min_size"],
                "max_size": spec["max_size"],
                "max_iops": spec["max_iops"],
                "max_throughput": spec["max_throughput"],
            }
        )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return items


def inventory_database_storage_prices(vendor):
    vendor.progress_tracker.start_task(name="Fetching Cloud SQL SKU(s)", total=None)
    skus = _cloud_sql_skus()
    vendor.progress_tracker.hide_task()

    items = []
    seen: set[tuple[str, str]] = set()
    vendor.progress_tracker.start_task(
        name="Processing database_storage_price(s)", total=len(skus)
    )
    for sku in skus:
        storage_id = _pg_storage_id(sku.description or "")
        if not storage_id:
            vendor.progress_tracker.advance_task()
            continue

        unit_price = _sku_unit_price(sku)
        if unit_price is None:
            vendor.progress_tracker.advance_task()
            continue
        usage_unit = (
            sku.pricing_info[0].pricing_expression.usage_unit
            if sku.pricing_info
            else ""
        )
        if usage_unit == "GiBy.mo":
            monthly = unit_price
        elif usage_unit == "GiBy.h":
            monthly = unit_price * 730
        else:
            vendor.progress_tracker.advance_task()
            continue

        tiered = sku.pricing_info[0].pricing_expression.tiered_rates
        currency = tiered[0].unit_price.currency_code or "USD"
        for region in vendor.regions:
            if region.api_reference not in sku.service_regions:
                continue
            key = (region.region_id, storage_id)
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "database_storage_id": storage_id,
                    "unit": PriceUnit.GB_MONTH,
                    "price": monthly,
                    "price_upfront": 0,
                    "price_tiered": [],
                    "currency": currency,
                }
            )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return items
