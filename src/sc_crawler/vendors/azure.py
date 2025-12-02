from functools import cache
from os import environ
from re import compile as recompile
from time import sleep
from typing import List, Optional

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.resource import ResourceManagementClient, SubscriptionClient
from cachier import cachier
from requests import Session as request_session

from ..logger import logger
from ..lookup import map_compliance_frameworks_to_vendor
from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    Disk,
    PriceUnit,
    StorageType,
    TrafficDirection,
)
from ..tables import Vendor
from ..utils import list_search, scmodels_to_dict
from ..vendor_helpers import preprocess_servers

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
def _compute_resources() -> List[dict]:
    resources = []
    for resource in _compute_client().resource_skus.list():
        resources.append(resource.as_dict())
    return resources


@cachier()
def _servers() -> List[dict]:
    servers = [
        s for s in _compute_resources() if s["resource_type"] == "virtualMachines"
    ]
    # dedupe same servers in different regions
    servers = {s["name"]: s for s in servers}
    servers = list(servers.values())
    return servers


@cache
def _prices(url_params: Optional[str] = None) -> List[dict]:
    ratelimit_reached = 0
    session = request_session()
    data = []
    next_url = "https://prices.azure.com/api/retail/prices"
    if url_params:
        next_url += "?" + url_params
    while next_url:
        response = session.get(next_url)
        # handle rate limiting
        headers = response.headers
        remaining = headers.get("x-ms-ratelimit-remaining-retailPrices-requests", 0)
        if response.status_code == 429 or int(remaining) == 0:
            ratelimit_reached += 1
            if ratelimit_reached > 5:
                raise HttpResponseError(
                    "Retail Prices API rate limit reached 5 times, giving up: "
                    + response.content.decode("utf-8")
                )
            logger.info("Retail Prices API rate limit reached, sleep for 60 seconds.")
            sleep(60 + 5)
        # go to next page
        elif response.status_code == 200:
            json = response.json()
            next_url = json.get("NextPageLink")
            data += json["Items"]
        else:
            raise HttpResponseError(response.content)
    return data


# ##############################################################################
# Internal helpers


SERVER_FEATURES = {
    # a = AMD-based processor
    # b = Block Storage performance
    # d = diskful (that is, a local temp disk is present)
    # i = isolated size
    # l = low memory; a lower amount of memory than the memory intensive size
    # m = memory intensive; the most amount of memory in a particular size
    # p = ARM Cpu
    # t = tiny memory; the smallest amount of memory in a particular size
    # s = Premium Storage capable, including possible use of Ultra SSD
    "a": "AMD processor",
    "p": "ARM processor",
    "b": "Block Storage performance",
    "d": "Local Disk",
    "i": "Isolated",
    "l": "Low Memory",
    "m": "Memory Intensive",
    "t": "Tiny Memory",
    "s": "Premium Storage capable",
    # not part of the official docs, searched at random places
    "r": "RDMA capable",
    "e": "Memory Optimized",  # Standard_DC2es_v5
    "x": "Unmatched Memory Capacity",  # TODO confirm
    "o": "o",  # TODO no information on this flag, e.g. Standard_L12aos_v4
}
"""Map lowercase chars from the server name to features."""

ARCHITECTURE_MAPPING = {
    "x64": CpuArchitecture.X86_64,
    "Arm64": CpuArchitecture.ARM64,
}

STORAGE_METER_MAPPING = {
    "P2 LRS Disk Mount": ("PremiumV2_LRS", 1),
    "P1 LRS Disk": ("Premium_LRS", 4),
    "P1 ZRS Disk": ("Premium_ZRS", 4),
    "E1 LRS Disk": ("StandardSSD_LRS", 4),
    "E1 ZRS Disk": ("StandardSSD_ZRS", 4),
    "S4 LRS Disk": ("Standard_LRS", 32),
    "Ultra LRS Provisioned Capacity": ("UltraSSD_LRS", 1),
}
"""Map Storage price meter names to the Storage name and the related disk's size."""


def _parse_server_name(name):
    """Extract information from the server name/size.

    Based on <https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/overview>."""

    name_pattern = recompile(
        # there is a constant prefix (Standard_), and there used to be Basic_
        # servers as well, but the latter were deprecated in Aug 2024
        r"((?P<prefix>[A-Za-z]+)_)"
        # first ALLCAPS chars are the family name (we don't care about the subfamily for now)
        r"(?P<family>[A-Z]+)"
        r"(?P<vcpus>[0-9]+)"
        r"(-(?P<constrained_vcpus>\d+))?"
        r"(?P<features>[a-z]*)"
        # spacers are odd .. not only accelerators, but e.g. `Standard_M416s_8_v2`
        r"(_(?P<spacers>[_A-Za-z0-9]*?))?"
        r"(?:v(?P<version>\d+))?"
        r"(_(?P<suffix>([A-Za-z0-9]*)))?$"
    )
    name_match = name_pattern.match(name)
    if not name_match:
        raise ValueError(f"Server name '{name}' does not match the expected format.")
    data = name_match.groupdict()

    # a = AMD-based processor
    # b = Block Storage performance
    # d = diskful (that is, a local temp disk is present)
    # i = isolated size
    # l = low memory; a lower amount of memory than the memory intensive size
    # m = memory intensive; the most amount of memory in a particular size
    # p = ARM Cpu
    # t = tiny memory; the smallest amount of memory in a particular size
    # s = Premium Storage capable, including possible use of Ultra SSD
    features = [char for char in data["features"]] if data["features"] else []

    accelerators = any(
        [
            s in ["A100", "H100", "MI300X", "V620", "A10"]
            for s in (data.get("spacers") or "").split("_")
        ]
    )

    family = data["family"]
    vcpus = int(data["vcpus"])
    # accelerators are not always mentioned in the old server names, so we need a manual mapping
    # which will be overwritten by the GPU count from HW inspection if we can start the node
    gpus = 0
    if family in ["NC", "ND", "NG", "NV"]:
        # default to one, list all the exceptions below
        # note that some servers come with a fraction of a GPU, but we need int
        gpus = 1
        if family == "NC":
            if vcpus == 24:
                # Standard_NC24ads_A100_v4 has only 1 GPU,
                # but Standard_NC24(r) has 4x Tesla K80
                if not accelerators:
                    gpus = 4
            if vcpus in [12, 80]:
                # Standard_NC48ads_A100_v4
                gpus = 2
            if vcpus in [64, 96]:
                # Standard_NC96ads_A100_v4
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

    return (family, features, gpus)


def _standardize_server(server: dict, vendor) -> dict:
    # example server dict:
    # {
    #     'resource_type': 'virtualMachines',
    #     'name': 'Standard_L80as_v3',
    #     'tier': 'Standard',
    #     'size': 'L80as_v3',
    #     'family': 'standardLASv3Family',
    #     'locations': ['WestUS3'],
    #     'location_info': [{'location': 'WestUS3', 'zones': ['1', '3', '2'], 'zone_details': [{'capabilities': [{'name': 'UltraSSDAvailable', 'value': 'True'}]}]}],
    #     'capabilities': [
    #         {'name': 'MaxResourceVolumeMB', 'value': '819200'},
    #         {'name': 'OSVhdSizeMB', 'value': '1047552'},
    #         {'name': 'vCPUs', 'value': '80'},
    #         {'name': 'MemoryPreservingMaintenanceSupported', 'value': 'True'},
    #         {'name': 'HyperVGenerations', 'value': 'V1,V2'},
    #         {'name': 'SupportedEphemeralOSDiskPlacements', 'value': 'ResourceDisk'},
    #         {'name': 'MemoryGB', 'value': '640'},
    #         {'name': 'MaxDataDiskCount', 'value': '32'},
    #         {'name': 'CpuArchitectureType', 'value': 'x64'},
    #         {'name': 'LowPriorityCapable', 'value': 'True'},
    #         {'name': 'PremiumIO', 'value': 'True'},
    #         {'name': 'VMDeploymentTypes', 'value': 'IaaS'},
    #         {'name': 'vCPUsAvailable', 'value': '80'},
    #         {'name': 'vCPUsPerCore', 'value': '2'},
    #         {'name': 'CombinedTempDiskAndCachedIOPS', 'value': '40000'},
    #         {'name': 'CombinedTempDiskAndCachedReadBytesPerSecond', 'value': '800000000'},
    #         {'name': 'CombinedTempDiskAndCachedWriteBytesPerSecond', 'value': '800000000'},
    #         {'name': 'UncachedDiskIOPS', 'value': '80000'},
    #         {'name': 'UncachedDiskBytesPerSecond', 'value': '1400000000'},
    #         {'name': 'NvmeDiskSizeInMiB', 'value': '18310546'},
    #         {'name': 'NvmeSizePerDiskInMiB', 'value': '1831054'},
    #         {'name': 'EphemeralOSDiskSupported', 'value': 'True'},
    #         {'name': 'EncryptionAtHostSupported', 'value': 'True'},
    #         {'name': 'CapacityReservationSupported', 'value': 'False'},
    #         {'name': 'AcceleratedNetworkingEnabled', 'value': 'True'},
    #         {'name': 'RdmaEnabled', 'value': 'False'},
    #         {'name': 'MaxNetworkInterfaces', 'value': '8'}
    #     ],
    #     'restrictions': [
    #         {'type': 'Location', 'values': ['WestUS3'], 'restriction_info': {'locations': ['WestUS3']}, 'reason_code': 'NotAvailableForSubscription'},
    #         {'type': 'Zone', 'values': ['WestUS3'], 'restriction_info': {'locations': ['WestUS3'], 'zones': ['1', '2', '3']}, 'reason_code': 'NotAvailableForSubscription'}
    #     ]
    # }
    family, features, gpus = _parse_server_name(server["name"])
    # override family from SKU listing
    family = server["family"].removeprefix("standard").removesuffix("Family")

    def capability(name: str, default=None) -> str:
        try:
            return list_search(server["capabilities"], "name", name)["value"]
        except Exception:
            return default

    architecture = ARCHITECTURE_MAPPING[capability("CpuArchitectureType")]
    # construct a server description as Azure doesn't provide one
    description = family + " family"
    description_extras = [SERVER_FEATURES[f] for f in features]
    if not set(["a", "p"]).intersection(features):
        description_extras.append("Intel processor")
    for description_extra in description_extras:
        description = description + " [" + description_extra + "]"
    description = description + " " + capability("vCPUs") + " vCPU"
    if int(capability("vCPUs")) > 1:
        description = description + "s"
    # no info on actual drives, but at least split for temp and NVMe disks
    storages = []
    # temp disk, values might be off, see e.g. DC1s_v2 reporting 51200 MB and showing 50 GiB in docs
    if capability("MaxResourceVolumeMB"):
        storages.append(
            Disk(
                size=round(float(capability("MaxResourceVolumeMB")) / 1e3),
                storage_type="ssd",
                description="temp disk",
            )
        )
    # NVMe disks are explicitely reported in base 2 unit
    if capability("NvmeDiskSizeInMiB"):
        storages.append(
            Disk(
                size=round(float(capability("NvmeDiskSizeInMiB")) * 1024**2 / 1e9),
                storage_type="nvme ssd",
            )
        )
    return {
        "vendor_id": vendor.vendor_id,
        "server_id": server["name"],
        "name": server["name"].removeprefix("Standard_"),
        "description": description,
        "api_reference": server["name"],
        "display_name": server["name"].removeprefix("Standard_"),
        "family": family,
        "vcpus": int(capability("vCPUs")),
        "hypervisor": "Microsoft Hyper-V",
        "cpu_allocation": (
            CpuAllocation.BURSTABLE
            if family.startswith("B")
            else CpuAllocation.DEDICATED
        ),
        "cpu_architecture": (
            CpuArchitecture.ARM64 if architecture == "arm64" else CpuArchitecture.X86_64
        ),
        "memory_amount": float(capability("MemoryGB")) * 1024,  # MiB
        "gpu_count": gpus,
        "storage_size": round(sum([s.size for s in storages])),  # int GB
        "storages": storages,
        "inbound_traffic": 0,
        "outbound_traffic": 0,
        "ipv4": 0,
    }


def _inventory_server_prices(vendor: Vendor, allocation: Allocation) -> List[dict]:
    # https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices
    vendor.progress_tracker.start_task(
        name="Fetching server_price(s) from the Azure API", total=None
    )
    # need to fetch ~200k items as filtering doesn't allow a combination of
    # not() and contains()/endswith(), so filtering on the client side below
    #   - not(contains(meterName, 'Low Priority'))
    #   - not(endswith(productName, 'Windows'))
    #   - not(endswith(productName, 'CloudServices'))
    retail_prices = _prices(
        "$filter=serviceName eq 'Virtual Machines' and priceType eq 'Consumption'"
    )
    vendor.progress_tracker.hide_task()

    vendor.progress_tracker.start_task(
        name="Preprocess ondemand server_price(s)", total=len(retail_prices)
    )

    server_ids = [n.api_reference for n in vendor.servers]
    region_ids = [n.api_reference for n in vendor.regions]
    regions = scmodels_to_dict(vendor.regions, keys=["api_reference"])

    prices = []
    for retail_price in retail_prices:
        # we don't track Low Priority pricing (using Spot instead)
        if "Low Priority" in retail_price["meterName"]:
            continue
        # don't track Windows pricing, or the Azure Cloud Services pricing either
        if retail_price["productName"].endswith(
            ("Windows", "CloudServices", "Cloud Services")
        ):
            continue
        # drop records related to unknown server types and/or regions
        if retail_price["armSkuName"] not in server_ids:
            continue
        if retail_price["armRegionName"] not in region_ids:
            continue
        # filter for ondemand or spot prict
        is_spot = "Spot" in retail_price["skuName"]
        if (allocation == Allocation.ONDEMAND and is_spot) or (
            allocation == Allocation.SPOT and not is_spot
        ):
            continue
        # sometimes Azure reports zero price for a server, skip it
        if retail_price["retailPrice"] == 0:
            continue
        region = regions.get(retail_price["armRegionName"])
        for zone in region.zones:
            prices.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "zone_id": zone.zone_id,
                    "server_id": retail_price["armSkuName"],
                    "operating_system": "Linux",
                    "allocation": allocation,
                    "unit": PriceUnit.HOUR,
                    "price": retail_price["retailPrice"],
                    "price_upfront": 0,
                    "price_tiered": [],
                    "currency": retail_price["currencyCode"],
                }
            )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return prices


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
        "southcentralusstg": {
            "country_id": "US",
            "state": "Texas",
            "city": "San Antonio",
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
        "chilecentral": {
            "country_id": "CL",
            "city": "Santiago",
            # coming soon
            "founding_year": 2025,
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
        "newzealandnorth": {
            "country_id": "NZ",
            "city": "Auckland",
            "founding_year": 2024,
            "green_energy": False,
        },
        "indonesiacentral": {
            "country_id": "ID",
            "city": "Jakarta",
            # coming soon
            "founding_year": 2025,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "malaysiawest": {
            "country_id": "MY",
            "city": "Kuala Lumpur",
            # coming soon
            "founding_year": 2025,
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
            "country_id": "GB",
            "city": "London",
            "founding_year": 2016,
            # unknown as no sustainability fact sheet found
            "green_energy": False,
        },
        "ukwest": {
            "country_id": "GB",
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
        "belgiumcentral": {
            "country_id": "BE",
            "founding_year": 2025,
            # unknown as no sustainability fact sheet found
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
        "austriaeast": {
            "country_id": "AT",
            "city": "Vienna",
            "founding_year": 2025,
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
        if region["metadata"]["region_type"] != "Physical":
            continue
        # no idea what are these
        if region["name"].endswith("stg"):
            continue
        # not production region?
        # https://github.com/Azure/azure-dev/issues/2165#issuecomment-1542948509
        if region["name"] == "brazilus":
            continue
        # exclude for now as this new region is popping up and being removed
        # from their API response randomly, so messing with git history
        if region["name"] == "newzealandnorth":
            continue
        manual_data = manual_datas.get(region["name"])
        if not manual_data:
            raise KeyError(f"No manual data found for {region['name']}.")
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
                    "display_name": region.region_id + "-" + zone,
                }
            )
    return items


def inventory_servers(vendor):
    """List all available instance types in all regions."""
    servers = _servers()
    for i in range(len(servers) - 1, -1, -1):
        name = servers[i].get("name")
        # drop Basic servers as to be deprecated by Aug 2024
        if name.startswith("Basic"):
            vendor.log(f"Excluding deprecated: {name}")
            servers.pop(i)
        # servers that are likely to be not available, with zero pricing
        if name.endswith("Promo"):
            vendor.log(f"Excluding nonsense pricing: {name}")
            servers.pop(i)
        # servers probably not intended for our eyes
        if "Internal" in name:
            vendor.log(f"Excluding internal server: {name}")
            servers.pop(i)
        # servers randomly switching between active/inactive status
        # TODO review from time to time
        if name in ["Standard_M896ixds_32_v3", "Standard_M64-32bds_1_v3"]:
            vendor.log(f"Excluding server with questionable availability: {name}")
            servers.pop(i)
    servers = preprocess_servers(servers, vendor, _standardize_server)
    return servers


def inventory_server_prices(vendor):
    """List all known server ondemand prices in all regions using the Azure Retail Pricing API.

    More information: <https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices>.
    """
    return _inventory_server_prices(vendor, Allocation.ONDEMAND)


def inventory_server_prices_spot(vendor):
    """List all known server spot prices in all regions using the Azure Retail Pricing API.

    See details at [inventory_server_prices][sc_crawler.vendors.azure.inventory_server_prices].
    """
    return _inventory_server_prices(vendor, Allocation.SPOT)


def inventory_storages(vendor):
    """List all storage options via the Compute resource manager client.

    For more information, see <https://learn.microsoft.com/en-us/azure/virtual-machines/disks-types>.
    """
    vendor.progress_tracker.start_task(
        name="Fetching list of compute resources", total=None
    )

    disks = []
    for resource in _compute_resources():
        if resource["resource_type"] == "disks":
            disks.append(resource)

    disks = list({d["name"]: d for d in disks}.values())
    vendor.progress_tracker.hide_task()

    items = []
    for disk in disks:

        def _search(values):
            return list_search(disk["capabilities"], "name", values)["value"]

        storage_type = (
            StorageType.HDD
            if "Standard" in disk["name"] and "SSD" not in disk["name"]
            else StorageType.SSD
        )
        redundancy_type = (
            "Locally Redundant Storage"
            if "LRS" in disk["name"]
            else "Zone-Redundant Storage"
        )
        description = f"{disk['tier']} tier {storage_type.name} ({redundancy_type})"

        items.append(
            {
                "storage_id": disk["name"],
                "vendor_id": vendor.vendor_id,
                "name": disk["name"],
                "description": description,
                "storage_type": storage_type,
                "max_iops": _search(["MaxIOpsReadWrite", "MaxIOps"]),
                "max_throughput": _search(
                    ["MaxBandwidthMBpsReadWrite", "MaxBandwidthMBps"]
                ),
                # NOTE this is 16TB for most drives?!
                "min_size": _search("MinSizeGiB"),
                "max_size": _search("MaxSizeGiB"),
            }
        )
    return items


def inventory_storage_prices(vendor):
    """Look up Storage prices via the Azure Retail Prices API.

    For more information, see <https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices>.
    """
    vendor.progress_tracker.start_task(
        name="Fetching list of storage resources", total=None
    )
    retail_prices = _prices("$filter=serviceName eq 'Storage'")
    vendor.progress_tracker.hide_task()

    regions = scmodels_to_dict(vendor.regions, keys=["region_id"])
    storages = scmodels_to_dict(vendor.storages, keys=["storage_id"])

    items = []
    for p in retail_prices:
        mapping = STORAGE_METER_MAPPING.get(p["meterName"])
        if (
            mapping
            and mapping[0] in storages.keys()
            and p["armRegionName"] in regions.keys()
        ):
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": p["armRegionName"],
                    "storage_id": mapping[0],
                    "unit": PriceUnit.GB_MONTH,
                    "price": p["retailPrice"] / mapping[1],
                    "currency": p["currencyCode"],
                }
            )
    return items


def inventory_traffic_prices(vendor):
    """Look up Internet Egress/Ingress prices via the Azure Retail Prices API.

    For more information, see <https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices>.
    """

    def get_tiers(prices: List[dict]) -> List[dict]:
        def prep_tiers(d: dict) -> dict:
            return {
                "lower": d.get("tierMinimumUnits", 0),
                "price": d["retailPrice"],
            }

        tiers = [prep_tiers(p) for p in prices]
        tiers.sort(key=lambda x: x.get("lower"))
        for i in range(len(tiers)):
            if i == len(tiers) - 1:
                tiers[i]["upper"] = "Infinity"
            else:
                tiers[i]["upper"] = tiers[i + 1]["lower"]
        return tiers

    def by_region(prices: List[dict], region: str) -> List[dict]:
        return [p for p in prices if p["armRegionName"] == region]

    vendor.progress_tracker.start_task(
        name="Fetching list of traffic prices", total=None
    )
    inbound_prices = _prices(
        "$filter=serviceFamily eq 'Networking' and meterName eq 'Standard Data Transfer In'"
    )
    outbound_prices = _prices(
        "$filter=serviceFamily eq 'Networking' and "
        "meterName eq 'Standard Data Transfer Out' and "
        "productName eq 'Bandwidth - Routing Preference: Internet'"
    )
    vendor.progress_tracker.hide_task()

    items = []
    regions = scmodels_to_dict(vendor.regions, keys=["api_reference"])
    for region in regions.values():
        for direction in ["inbound", "outbound"]:
            prices = inbound_prices if direction == "inbound" else outbound_prices
            tiers = get_tiers(by_region(prices, region.api_reference))
            if tiers:
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": region.region_id,
                        "price": max([t["price"] for t in tiers]),
                        "price_tiered": tiers,
                        "currency": prices[0].get("currencyCode", "USD"),
                        "unit": PriceUnit.GB_MONTH,
                        "direction": (
                            TrafficDirection.IN
                            if direction == "inbound"
                            else TrafficDirection.OUT
                        ),
                    }
                )
    return items


def inventory_ipv4_prices(vendor):
    """Look up Internet Egress/Ingress prices via the Azure Retail Prices API.

    For more information, see <https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices>.
    """

    vendor.progress_tracker.start_task(
        name="Fetching list of traffic prices", total=None
    )
    prices = _prices(
        "$filter=serviceFamily eq 'Networking' and "
        "meterName eq 'Basic IPv4 Dynamic Public IP' and "
        "type eq 'Consumption'"
    )
    vendor.progress_tracker.hide_task()

    items = []
    regions = scmodels_to_dict(vendor.regions, keys=["api_reference"])
    for region in regions.values():
        price = list_search(prices, "armRegionName", region.api_reference)
        if price:
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "price": price["retailPrice"],
                    "currency": price.get("currencyCode", "USD"),
                    "unit": PriceUnit.HOUR,
                }
            )
    return items
