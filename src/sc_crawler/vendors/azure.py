from functools import cache
from os import environ
from re import search
from typing import List

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.resource import ResourceManagementClient, SubscriptionClient
from cachier import cachier

from ..lookup import map_compliance_frameworks_to_vendor
from ..vendor_helpers import parallel_fetch_servers, preprocess_servers
from ..table_fields import CpuAllocation, CpuArchitecture


from sc_crawler.lookup import map_compliance_frameworks_to_vendor
from sc_crawler.vendor_helpers import parallel_fetch_servers, preprocess_servers
from sc_crawler.table_fields import CpuAllocation, CpuArchitecture

credential = DefaultAzureCredential()


# ##############################################################################
# Cached Azure client wrappers


@cache
def _subscription_client() -> SubscriptionClient:
    return SubscriptionClient(credential)


@cache
def _subscription_id() -> str:
    """Get Subscription ID.

    Read from the `AZURE_SUBSCRIPTION_ID` environment variable,
    otherwise use first subcription found in the account.
    """
    return environ.get(
        "AZURE_SUBSCRIPTION_ID",
        default=next(_subscription_client().subscriptions.list()).subscription_id,
    )


@cache
def _resource_client() -> ResourceManagementClient:
    return ResourceManagementClient(credential, _subscription_id())


@cache
def _compute_client() -> ComputeManagementClient:
    return ComputeManagementClient(credential, _subscription_id())


@cachier()
def _regions() -> List[dict]:
    locations = []
    for location in _subscription_client().subscriptions.list_locations(
        _subscription_id()
    ):
        locations.append(location.as_dict())
    return locations


@cachier()
def _resources(namespace: str) -> List[dict]:
    resources = []
    for resource in _resource_client().providers.get(namespace).resource_types:
        resources.append(resource.as_dict())
    return resources


@cachier()
def _servers(region: str) -> List[dict]:
    servers = []
    try:
        for server in _compute_client().virtual_machine_sizes.list(region):
            servers.append(server.as_dict())
    except HttpResponseError:
        pass
    return servers


# ##############################################################################
# Internal helpers


def _parse_server_name(name):
    """Extract information from the server name/size.

    Based on <https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview>."""
    # drop the constant prefix
    name = name.removeprefix("Standard_")
    # first ALLCAPS chars are the family name (we don't care about the subfamily for now)
    family = search(r"^([A-Z]*)", name).group(1)
    name = name.removeprefix(family)
    vcpus = int(search(r"^([0-9]*)", name).group(1))
    name = name.removeprefix(str(vcpus))
    # drop constrained vCPU count
    contrained_vcpus = search(r"^-([0-9])*", name)
    if contrained_vcpus:
        contrained_vcpus = contrained_vcpus.group(1)
        name.removeprefix("-" + contrained_vcpus)
    # a = AMD-based processor
    # b = Block Storage performance
    # d = diskful (that is, a local temp disk is present)
    # i = isolated size
    # l = low memory; a lower amount of memory than the memory intensive size
    # m = memory intensive; the most amount of memory in a particular size
    # p = ARM Cpu
    # t = tiny memory; the smallest amount of memory in a particular size
    # s = Premium Storage capable, including possible use of Ultra SSD
    features = []
    if search(r"^[a-z]*", name):
        features = [char for char in search(r"^([a-z]*)", name).group(1)]
    # the only way to find out if a server is x86 or ARM
    architecture = "x86_64"
    if "p" in features:
        architecture = "arm64"
    # accelerators are mentioned in the name of the newer servers
    accelerators = search(r"((A100|H100|MI300X|V620|A10))", name)
    if accelerators:
        accelerators = accelerators.group(1)
    # but accelerators are not mentioned in the old server names, so we need a manual mapping
    gpus = 0
    if family in ["NC", "ND", "NG", "NV"]:
        # default to one, list all the exceptions below
        # note that some servers come with a fraction of a GPU, but we need int
        gpus = 1
        if family == "NC":
            if vcpus == 24:
                # Standard_NC24ads_A100_v4 has only 1 GPU, but Standard_NC24(r) has 4x Tesla K80
                if not accelerators:
                    gpus = 4
            if vcpus in [12, 80]:
                gpus = 2
            if vcpus in [64]:
                gpus = 4
        if family == "ND":
            if vcpus in [12]:
                gpus = 2
            if vcpus in [24]:
                gpus = 4
            if vcpus in [40, 96]:
                gpus = 8
        if family == "NG":
            # all NG servers has 1 or just a fraction of a GPU
            pass
        if family == "NV":
            if vcpus in [24, 72]:
                gpus = 2
            if vcpus in [48]:
                gpus = 4
    return (family, architecture, gpus)


def _standardize_server(server: dict, vendor) -> dict:
    # example server dict:
    #   {'name': 'Standard_L64as_v3', 'number_of_cores': 64,
    #    'os_disk_size_in_mb': 1047552, 'resource_disk_size_in_mb': 655360,
    #    'memory_in_mb': 524288, 'max_data_disk_count': 32}
    family, architecture, gpus = _parse_server_name(server["name"])
    return {
        "vendor_id": vendor.vendor_id,
        "server_id": server["name"],
        "name": server["name"],
        "vcpus": server["number_of_cores"],
        "hypervisor": "Microsoft Hyper-V,",
        "cpu_allocation": (
            CpuAllocation.BURSTABLE if family == "B" else CpuAllocation.DEDICATED
        ),
        "cpu_architecture": (
            CpuArchitecture.ARM64 if architecture == "arm64" else CpuArchitecture.X86_64
        ),
        "memory_amount": server["memory_in_mb"],
        "gpu_count": gpus,
        # not including os_disk_size_in_mb, as that's not mentioned in the docs,
        # see e.g. https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/general-purpose/dsv5-series
        "storage_size": server["resource_disk_size_in_mb"] / 1024,
        "inbound_traffic": 0,
        "outbound_traffic": 0,
        "ipv4": 0,
    }


# ##############################################################################
# Public methods to fetch data


def inventory_compliance_frameworks(vendor):
    """Manual list of known compliance frameworks at Azure.

    Data collected from <https://learn.microsoft.com/en-us/azure/compliance/>.
    """
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id, ["hipaa", "soc2t2", "iso27001"]
    )


def inventory_regions(vendor):
    """List all regions via API call.

    Location (country and state) and founding year
    were collected manually from
    <https://datacenters.microsoft.com/globe/explore/>
    and its underlying JSON at
    <https://datacenters.microsoft.com/globe/data/geo/regions.json>.

    City and the energy source information was collected from
    the sustainability fact sheets referenced in the above page and JSON.

    Coordinates were provided by the Microsoft API, which doesn't seem
    to be very reliable.
    """

    manual_datas = {
        # Canada
        "canadaeast": {
            "country_id": "CA",
            "state": "Quebec",
            "city": "Quebec City",
            "founding_year": 2016,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "canadacentral": {
            "country_id": "CA",
            "city": "Toronto",
            "founding_year": 2016,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        # United States
        "centralus": {
            "country_id": "US",
            "state": "Iowa",
            "founding_year": 2014,
            "green_energy": True,
        },
        "centraluseuap": {
            "country_id": "US",
            "state": "Iowa",
            "green_energy": True,
        },
        "eastus": {
            "country_id": "US",
            "city": "Boydton",
            "state": "Virginia",
            # official site says 2014 with a dead link, but it was 2012 as per
            # https://web.archive.org/web/20120530115120/http:/blogs.msdn.com/b/windowsazure/archive/2012/04/05/announcing-new-datacenter-options-for-windows-azure.aspx
            "founding_year": 2012,
            "green_energy": False,
        },
        "eastusstg": {
            "country_id": "US",
            "state": "Virginia",
            "green_energy": False,
        },
        "eastus2": {
            "country_id": "US",
            "city": "Boydton",
            "state": "Virginia",
            # official site says 2012 with a dead link, but it was 2014 as per
            # https://azure.microsoft.com/en-us/updates/general-availability-microsoft-azure-us-central-and-us-east-2-regions/
            "founding_year": 2014,
            "green_energy": False,
        },
        "eastus2euap": {
            "country_id": "US",
            "state": "Virginia",
            "green_energy": False,
        },
        "northcentralus": {
            "country_id": "US",
            "city": "Chicago",
            "state": "Illinois",
            "founding_year": 2009,
            "green_energy": False,
        },
        "southcentralus": {
            "country_id": "US",
            "state": "Texas",
            "city": "San Antonio",
            "founding_year": 2008,
            "green_energy": True,
        },
        "westcentralus": {
            "country_id": "US",
            "state": "Wyoming",
            "city": "Cheyenne",
            "founding_year": 2016,
            "green_energy": False,
        },
        "westus": {
            "country_id": "US",
            "state": "California",
            "founding_year": 2012,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "westus2": {
            "country_id": "US",
            "state": "Washington",
            "founding_year": 2007,
            "green_energy": False,
        },
        "westus3": {
            "country_id": "US",
            "state": "Arizona",
            "city": "Phoenix",
            "founding_year": 2021,
            "green_energy": False,
        },
        # Mexico
        "mexicocentral": {
            "country_id": "ZA",
            "state": "Querétaro",
            "founding_year": 2024,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        # South America
        "brazilsouth": {
            "country_id": "BR",
            "state": "Campinas",
            "founding_year": 2014,
            "green_energy": False,
        },
        "brazilsoutheast": {
            "country_id": "US",
            "city": "Rio de Janeiro",
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        # not production region?
        # https://github.com/Azure/azure-dev/issues/2165#issuecomment-1542948509
        "brazilus": {
            "country_id": "BR",
        },
        # Asia Pacific
        "australiacentral": {
            "country_id": "AU",
            "city": "Canberra",
            "founding_year": 2018,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "australiacentral2": {
            "country_id": "AU",
            "city": "Canberra",
            "founding_year": 2018,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "australiaeast": {
            "country_id": "AU",
            "city": "Sydney",
            "state": "New South Wales",
            "founding_year": 2014,
            "green_energy": False,
        },
        "australiasoutheast": {
            "country_id": "AU",
            "city": "Melbourne",
            "state": "Victoria",
            "founding_year": 2014,
            "green_energy": False,
        },
        "eastasia": {
            "country_id": "HK",
            "founding_year": 2010,
            "green_energy": False,
        },
        "southeastasia": {
            "country_id": "SG",
            "city": "Singapore",
            "founding_year": 2010,
            "green_energy": False,
        },
        "japaneast": {
            "country_id": "JP",
            "city": "Tokyo",
            "founding_year": 2014,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "japanwest": {
            "country_id": "JP",
            "city": "Osaka",
            "founding_year": 2014,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "jioindiacentral": {
            "country_id": "IN",
            "city": "Nagpur",
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "jioindiawest": {
            "country_id": "IN",
            "city": "Jamnagar",
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "centralindia": {
            "country_id": "IN",
            "state": "Pune",
            "founding_year": 2015,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "southindia": {
            "country_id": "IN",
            "state": "Chennai",
            "founding_year": 2015,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "westindia": {
            "country_id": "IN",
            "state": "Mumbai",
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "koreacentral": {
            "country_id": "KR",
            "city": "Seoul",
            "founding_year": 2017,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "koreasouth": {
            "country_id": "KR",
            "city": "Busan",
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        # Europe
        "francecentral": {
            "country_id": "FR",
            "city": "Paris",
            "founding_year": 2018,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "francesouth": {
            "country_id": "FR",
            "city": "Marseille",
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "germanynorth": {
            "country_id": "DE",
            "city": "Berlin",
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "germanywestcentral": {
            "country_id": "DE",
            "city": "Frankfurt",
            "founding_year": 2019,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "italynorth": {
            "country_id": "IT",
            "city": "Milan",
            "founding_year": 2023,
            "green_energy": False,
        },
        "northeurope": {
            "country_id": "IE",
            "city": "Dublin",
            "founding_year": 2009,
            "green_energy": False,
        },
        "norwayeast": {
            "country_id": "NO",
            "city": "Oslo",
            "founding_year": 2019,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "norwaywest": {
            "country_id": "NO",
        },
        "polandcentral": {
            "country_id": "PL",
            "city": "Warsaw",
            "founding_year": 2023,
            "green_energy": False,
        },
        "spaincentral": {
            "country_id": "ES",
            "city": "Madrid",
            "founding_year": 2024,
            "green_energy": False,
        },
        "swedencentral": {
            "country_id": "SE",
            "city": "Gävle and Sandviken",
            "founding_year": 2021,
            "green_energy": False,
        },
        "switzerlandnorth": {
            "country_id": "CH",
            "city": "Zürich",
            "founding_year": 2019,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "switzerlandwest": {
            "country_id": "CH",
            "city": "Geneva",
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "uksouth": {
            "country_id": "UK",
            "city": "London",
            "founding_year": 2016,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "ukwest": {
            "country_id": "UK",
            "city": "Cardiff",
            "founding_year": 2017,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "westeurope": {
            "country_id": "NL",
            "founding_year": 2010,
            "green_energy": False,
        },
        # Middle East
        "israelcentral": {
            "country_id": "IL",
            "founding_year": 2023,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "qatarcentral": {
            "country_id": "QA",
            "city": "Doha",
            "founding_year": 2022,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "uaecentral": {
            "country_id": "AE",
            "city": "Abu Dhabi",
        },
        "uaenorth": {
            "country_id": "AE",
            "city": "Dubai",
            "founding_year": 2019,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        # Africa
        "southafricanorth": {
            "country_id": "ZA",
            "city": "Johannesburg",
            "founding_year": 2019,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "southafricawest": {
            "country_id": "ZA",
            "city": "Cape Town",
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        # China TODO enable
    }

    items = []
    for region in _regions():
        if region["metadata"]["region_type"] == "Physical":
            manual_data = manual_datas.get(region["name"], {})
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region["name"],
                    "name": region["display_name"],
                    "api_reference": region["name"],
                    "display_name": (
                        region["display_name"] + " (" + manual_data["country_id"] + ")"
                    ),
                    "country_id": manual_data["country_id"],
                    "state": manual_data.get("state"),
                    "city": manual_data.get("city"),
                    "address_line": None,
                    "zip_code": None,
                    "lat": region["metadata"]["latitude"],
                    "lon": region["metadata"]["longitude"],
                    "founding_year": manual_data.get("founding_year"),
                    "green_energy": manual_data.get("green_energy"),
                }
            )
    return items


def inventory_zones(vendor):
    """List all availability zones.

    API call to list existing availability zones ("1", "2", and "3")
    for each region, and creating a dummy "0" zone for the regions
    without availability zones.
    """
    items = []
    resources = _resources("Microsoft.Compute")
    locations = [i for i in resources if i["resource_type"] == "virtualMachines"][0]
    locations = {item["location"]: item["zones"] for item in locations["zone_mappings"]}
    # TODO parallelize
    for region in vendor.regions:
        # default to zone with 0 ID if there are no real availability zones
        region_zones = locations.get(region.name, ["0"])
        for zone in region_zones:
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "zone_id": zone,
                    "name": zone,
                    "api_reference": zone,
                    "display_name": zone,
                }
            )
    return items


def inventory_servers(vendor):
    """List all available instance types in all regions."""
    servers = parallel_fetch_servers(vendor, _servers, "name")
    # drop Basic servers as to be deprecated by Aug 2024
    for i in range(len(servers) - 1, -1, -1):
        name = servers[i].get("name")
        if name.startswith("Basic"):
            vendor.log(f"Excluding deprecated {name}")
            servers.pop(i)
    servers = preprocess_servers(servers, vendor, _standardize_server)
    return servers


def inventory_server_prices(vendor):
    items = []
    # for server in []:
    #     items.append({
    #         "vendor_id": ,
    #         "datacenter_id": ,
    #         "zone_id": ,
    #         "server_id": ,
    #         "operating_system": ,
    #         "allocation": Allocation....,
    #         "unit": "hourly",
    #         "price": ,
    #         "price_upfront": 0,
    #         "price_tiered": [],
    #         "currency": "USD",
    #     })
    return items


def inventory_server_prices_spot(vendor):
    return []


def inventory_storage(vendor):
    items = []
    # for storage in []:
    #     items.append(
    #         {
    #             "storage_id": ,
    #             "vendor_id": vendor.vendor_id,
    #             "name": ,
    #             "description": None,
    #             "storage_type": StorageType....,
    #             "max_iops": None,
    #             "max_throughput": None,
    #             "min_size": None,
    #             "max_size": None,
    #         }
    #     )
    return items


def inventory_storage_prices(vendor):
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "datacenter_id": ,
    #             "storage_id": ,
    #             "unit": PriceUnit.GB_MONTH,
    #             "price": ,
    #             "currency": "USD",
    #         }
    #     )
    return items


def inventory_traffic_prices(vendor):
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "datacenter_id": ,
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
    #             "datacenter_id": ,
    #             "price": ,
    #             "currency": "USD",
    #             "unit": PriceUnit.HOUR,
    #         }
    #     )
    return items


# names = [server.get("name") for server in servers]
# names.sort()
# for server in names:
#     print(server)

# for server in servers:
#     if server.get("name") == "Standard_D8s_v5":
#         break