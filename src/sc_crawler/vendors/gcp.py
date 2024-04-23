from concurrent.futures import ThreadPoolExecutor
from functools import cache
from itertools import chain, repeat
from logging import DEBUG
from re import sub
from typing import List

from cachier import cachier
from google.auth import default
from google.cloud import billing_v1, compute_v1

from ..lookup import map_compliance_frameworks_to_vendor
from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    PriceUnit,
    StorageType,
    TrafficDirection,
)
from ..tables import (
    Vendor,
    Zone,
)
from ..utils import nesteddefaultdict, scmodels_to_dict

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
                sku.category.resource_group in ["CPU", "RAM"]
                and "Custom" not in sku.description
                and "Sole Tenancy" not in sku.description
                and (
                    "Instance Core running in" in sku.description
                    or "Instance Ram running in" in sku.description
                )
            ):
                catgroup = sku.category.resource_group.lower()
                family = sub(r"^Spot Preemptible ", "", sku.description)
                family = sub(r" Instance.*", "", family)
                family = sub(r" AMD$", "", family)
                family = sub(r" Arm$", "", family)

                # extract instance family from description (?!)
                for k, v in SERVER_DESCRIPTION_TO_FAMILY.items():
                    if family == k:
                        family = v
                family = family.lower()

                for region in regions:
                    lookup[catgroup][family][region][allocation] = (price, currency)
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


def _inventory_server_prices(vendor: Vendor, allocation: Allocation) -> List[dict]:
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name"])
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
        if family == "n1":
            family = "m1"

        # price per instance or cpu/ram
        regions = [*skus["instance"][family].keys(), *skus["cpu"][family].keys()]
        assert len(regions) > 0

        for region in regions:
            # skip edge regions
            datacenter = datacenters.get(region)
            if datacenter is None:
                vendor.log(
                    f"Skip unknown '{region}' region for {server.name}",
                    DEBUG,
                )
                continue

            # try instance-level pricing
            if skus["instance"][family]:
                try:
                    price, currency = skus["instance"][family][region][
                        allocation.value.lower()
                    ]
                except ValueError:
                    vendor.log(
                        f"{allocation.value} price not found for '{server.name}' in '{region}'",
                        DEBUG,
                    )
                    continue
            # add ram and cpu prices
            elif skus["cpu"][family]:
                try:
                    price = (
                        skus["cpu"][family][region][allocation.value.lower()][0]
                        * server.vcpus
                        + skus["ram"][family][region][allocation.value.lower()][0]
                        * server.memory
                        / 1024
                    )
                    currency = skus["cpu"][family][region][allocation.value.lower()][1]
                except (ValueError, TypeError):
                    vendor.log(
                        f"{allocation.value} price not found for '{server.name}' in '{region}'",
                        DEBUG,
                    )
                    continue
            else:
                raise KeyError(f"SKU not found for {server.name}")

            for zone in datacenter.zones:
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "datacenter_id": datacenter.datacenter_id,
                        "zone_id": zone.zone_id,
                        "server_id": server.server_id,
                        "operating_system": "Linux",
                        "allocation": allocation,
                        "unit": PriceUnit.HOUR,
                        "price": round(price, 5),
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


def inventory_datacenters(vendor):
    """List all available GCP regions via API calls.

    Some data sources are not available from APIs, and were collected manually:
    - location: <https://cloud.google.com/compute/docs/regions-zones#available> and <https://en.wikipedia.org/wiki/Google_data_centers>
    - energy carbon data: <https://cloud.google.com/sustainability/region-carbon#data> and <https://github.com/GoogleCloudPlatform/region-carbon-info>
    - launch dates were collected from [Wikipedia](https://en.wikipedia.org/wiki/Google_Cloud_Platform#Regions_and_zones) and GCP blog posts, such as <https://medium.com/@retomeier/an-annotated-history-of-googles-cloud-platform-90b90f948920> and <https://cloud.google.com/blog/products/infrastructure/introducing-new-google-cloud-regions>

    Note that many GCP datacenters use more than 90% green energy,
    but the related flag in our database is set to `False` as not being 100%.
    """

    manual_data = {
        "africa-south1": {
            "country_id": "ZA",
            "city": "Johannesburg",
            # https://cloud.google.com/blog/products/infrastructure/heita-south-africa-new-cloud-region
            "founding_year": 2024,
            "green_energy": False,
        },
        "asia-east1": {
            "country_id": "TW",
            "state": "Changhua County",
            "founding_year": 2013,
            "green_energy": False,
        },
        "asia-east2": {
            "country_id": "HK",
            # https://cloud.google.com/blog/products/gcp/gcps-region-in-hong-kong-is-now-open
            "founding_year": 2018,
            "green_energy": False,
        },
        "asia-northeast1": {
            "country_id": "JP",
            "city": "Tokyo",
            "state": "Japan",
            "founding_year": 2016,
            "green_energy": False,
        },
        "asia-northeast2": {
            "country_id": "JP",
            "city": "Osaka",
            "founding_year": 2019,
            "green_energy": False,
        },
        "asia-northeast3": {
            "country_id": "KR",
            "city": "Seoul",
            "founding_year": 2020,
            "green_energy": False,
        },
        "asia-south1": {
            "country_id": "IN",
            "city": "Mumbai",
            "founding_year": 2017,
            "green_energy": False,
        },
        "asia-south2": {
            "country_id": "IN",
            "city": "Delhi",
            "founding_year": 2021,
            "green_energy": False,
        },
        "asia-southeast1": {
            "country_id": "SG",
            "city": "Jurong West",
            "founding_year": 2017,
            "green_energy": False,
        },
        "asia-southeast2": {
            "country_id": "ID",
            "city": "Jakarta",
            "founding_year": 2020,
            "green_energy": False,
        },
        "australia-southeast1": {
            "country_id": "AU",
            "city": "Sydney",
            "founding_year": 2017,
            "green_energy": False,
        },
        "australia-southeast2": {
            "country_id": "AU",
            "city": "Melbourne",
            "founding_year": 2021,
            "green_energy": False,
        },
        "europe-central2": {
            "country_id": "PL",
            "city": "Warsaw",
            "founding_year": 2021,
            "green_energy": False,
        },
        "europe-north1": {
            "country_id": "FI",
            "city": "Hamina",
            "founding_year": 2018,
            "green_energy": False,
        },
        "europe-southwest1": {
            "country_id": "ES",
            "city": "Madrid",
            "founding_year": 2022,
            "green_energy": False,
        },
        "europe-west1": {
            "country_id": "BE",
            "city": "St. Ghislain",
            # https://medium.com/@retomeier/an-annotated-history-of-googles-cloud-platform-90b90f948920
            "founding_year": 2015,
            "green_energy": False,
        },
        "europe-west10": {
            "country_id": "DE",
            "city": "Berlin",
            "founding_year": 2023,
            "green_energy": False,
        },
        "europe-west12": {
            "country_id": "IT",
            "city": "Turin",
            "founding_year": 2023,
            "green_energy": False,
        },
        "europe-west2": {
            "country_id": "GB",
            "city": "London",
            "founding_year": 2017,
            "green_energy": False,
        },
        "europe-west3": {
            "country_id": "DE",
            "city": "Frankfurt",
            "founding_year": 2017,
            "green_energy": False,
        },
        "europe-west4": {
            "country_id": "NL",
            "city": "Eemshaven",
            "founding_year": 2018,
            "green_energy": False,
        },
        "europe-west6": {
            "country_id": "CH",
            "city": "Zurich",
            "founding_year": 2019,
            "green_energy": False,
        },
        "europe-west8": {
            "country_id": "IT",
            "city": "Milan",
            "founding_year": 2022,
            "green_energy": False,
        },
        "europe-west9": {
            "country_id": "FR",
            "city": "Paris",
            "founding_year": 2022,
            "green_energy": False,
        },
        "me-central1": {
            "country_id": "QA",
            "city": "Doha",
            "founding_year": 2023,
            "green_energy": False,
        },
        "me-central2": {
            "country_id": "SA",
            "city": "Dammam",
            "founding_year": 2023,
            "green_energy": False,
        },
        "me-west1": {
            "country_id": "IL",
            "city": "Tel Aviv",
            "founding_year": 2022,
            "green_energy": False,
        },
        "northamerica-northeast1": {
            "country_id": "CA",
            "city": "Montréal",
            "founding_year": 2018,
            "green_energy": True,
        },
        "northamerica-northeast2": {
            "country_id": "CA",
            "city": "Toronto",
            "founding_year": 2021,
            "green_energy": False,
        },
        "southamerica-east1": {
            "country_id": "BR",
            "city": "Osasco",
            "state": "São Paulo",
            "founding_year": 2017,
            "green_energy": False,
        },
        "southamerica-west1": {
            "country_id": "CL",
            "city": "Santiago",
            "founding_year": 2021,
            "green_energy": False,
        },
        "us-central1": {
            "country_id": "US",
            "city": "Council Bluffs",
            "state": "Iowa",
            "founding_year": 2009,
            "green_energy": False,
        },
        "us-east1": {
            "country_id": "US",
            "city": "Moncks Corner",
            "state": "South Carolina",
            "founding_year": 2015,
            "green_energy": False,
        },
        "us-east4": {
            "country_id": "US",
            "city": "Ashburn",
            "state": "Virginia",
            "founding_year": 2017,
            "green_energy": False,
        },
        "us-east5": {
            "country_id": "US",
            "city": "Columbus",
            "state": "Ohio",
            "founding_year": 2022,
            "green_energy": False,
        },
        "us-south1": {
            "country_id": "US",
            "city": "Dallas",
            "state": "Texas",
            "founding_year": 2022,
            "green_energy": False,
        },
        "us-west1": {
            "country_id": "US",
            "city": "The Dalles",
            "state": "Oregon",
            "founding_year": 2016,
            "green_energy": False,
        },
        "us-west2": {
            "country_id": "US",
            "city": "Los Angeles",
            "state": "California",
            "founding_year": 2018,
            "green_energy": False,
        },
        "us-west3": {
            "country_id": "US",
            "city": "Salt Lake City",
            "state": "Utah",
            "founding_year": 2020,
            "green_energy": False,
        },
        "us-west4": {
            "country_id": "US",
            "city": "Las Vegas",
            "state": "Nevada",
            "founding_year": 2020,
            "green_energy": False,
        },
    }

    regions = _regions()
    items = []
    for region in regions:
        if region.name not in manual_data:
            raise KeyError(f"Unknown datacenter metadata for {region.name}")
        item = {
            "vendor_id": vendor.vendor_id,
            "datacenter_id": str(region.id),
            "name": region.name,
        }
        for k, v in manual_data[region.name].items():
            item[k] = v
        items.append(item)
    return items


def inventory_zones(vendor):
    """List all available GCP zones via API calls."""
    items = []
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name"])
    for zone in _zones():
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                # example `zone.region`:
                # https://www.googleapis.com/compute/v1/projects/algebraic-pier-412621/regions/us-east4
                "datacenter_id": datacenters[zone.region.split("/")[-1]].datacenter_id,
                "zone_id": str(zone.id),
                "name": zone.name,
            }
        )
    return items


def inventory_servers(vendor):
    """List all available GCP servers available in all zones."""
    vendor.progress_tracker.start_task(
        name="Scanning zone(s) for server(s)", total=len(vendor.zones)
    )

    def search_servers(zone: Zone, vendor: Vendor) -> List[dict]:
        zone_servers = []
        for server in _servers(zone.name):
            zone_servers.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "server_id": str(server.id),
                    "name": server.name,
                    "description": server.description,
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
                    "memory": server.memory_mb,
                    "gpu_count": (
                        server.accelerators[0].guest_accelerator_count
                        if server.accelerators
                        else 0
                    ),
                    "gpu_memory_min": None,
                    "gpu_memory_total": None,
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
                    "network_speed": None,
                    "inbound_traffic": 0,
                    "outbound_traffic": 0,
                    "ipv4": 0,
                }
            )
        vendor.log(f"{len(zone_servers)} server(s) found in {zone.name}.")
        vendor.progress_tracker.advance_task()
        return zone_servers

    with ThreadPoolExecutor(max_workers=8) as executor:
        servers = executor.map(search_servers, vendor.zones, repeat(vendor))
    servers = list(chain.from_iterable(servers))

    vendor.log(f"{len(servers)} server(s) found in {len(vendor.zones)} zones.")
    servers = list({p["name"]: p for p in servers}.values())
    vendor.log(f"{len(servers)} unique server(s) found.")
    vendor.progress_tracker.hide_task()
    return servers


def inventory_server_prices(vendor):
    """List all available GCP server ondemand prices in all datacenters."""
    return _inventory_server_prices(vendor, Allocation.ONDEMAND)


def inventory_server_prices_spot(vendor):
    """List all available GCP server spot prices in all datacenters."""
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
    vendor.progress_tracker.hide_task()
    return storages


def inventory_storage_prices(vendor):
    """List all available GCP disk storage prices in all datacenters."""
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name"])
    skus = _skus_dict()
    items = []
    for storage in vendor.storages:
        regions = skus["storage"][storage.name].keys()
        for region in regions:
            # skip edge regions
            datacenter = datacenters.get(region)
            if datacenter is None:
                vendor.log(
                    f"Skip unknown '{region}' region for {storage.name}",
                    DEBUG,
                )
                continue

            price, currency = skus["storage"][storage.name][region]["ondemand"]
            for zone in datacenter.zones:
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "datacenter_id": datacenter.datacenter_id,
                        "storage_id": storage.storage_id,
                        "unit": PriceUnit.GB_MONTH,
                        "price": price,
                        "currency": currency,
                    }
                )
    return items


def inventory_traffic_prices(vendor):
    """List inbound and outbound network traffic prices in all GCP datacenters."""
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name"])
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
        regions = sku.service_regions
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

        for region in regions:
            datacenter = datacenters.get(region)
            if datacenter is None:
                vendor.log(
                    f"Skip unknown '{region}' region for {sku.description}",
                    DEBUG,
                )
                continue
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "datacenter_id": datacenter.datacenter_id,
                    "price": max([t["price"] for t in price_tiers]),
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
    """List the price of an attached IPv4 address in all GCP datacenters.

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
    for datacenter in vendor.datacenters:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": datacenter.datacenter_id,
                "price": 0.005,
                "currency": "USD",
                "unit": PriceUnit.MONTH,
            }
        )
    return items
