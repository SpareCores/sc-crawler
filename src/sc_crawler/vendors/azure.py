from os import environ
from typing import List

from azure.identity import DefaultAzureCredential
from azure.mgmt.resource import ResourceManagementClient, SubscriptionClient
from azure.mgmt.resource.resources.v2022_09_01.models import ProviderResourceType
from azure.mgmt.resource.subscriptions.v2022_12_01.models import Location
from cachier import cachier

from ..lookup import map_compliance_frameworks_to_vendor

credential = DefaultAzureCredential()
subscription_client = SubscriptionClient(credential)

# use first subcription if not passed via env var
subscription_id = environ.get(
    "AZURE_SUBSCRIPTION_ID",
    default=next(subscription_client.subscriptions.list()).subscription_id,
)

resource_client = ResourceManagementClient(credential, subscription_id)


# ##############################################################################
# Cached Azure client wrappers


@cachier()
def _regions() -> List[Location]:
    locations = []
    for location in subscription_client.subscriptions.list_locations(subscription_id):
        locations.append(location.as_dict())
    return locations


@cachier()
def _resources(namespace: str) -> List[ProviderResourceType]:
    resources = []
    for resource in resource_client.providers.get(namespace).resource_types:
        resources.append(resource.as_dict())
    return resources


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
            if not manual_data:
                import pdb

                pdb.set_trace()

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
                    "display_name": zone,
                }
            )
    return items


def inventory_servers(vendor):
    items = []
    # for server in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "server_id": ,
    #             "name": ,
    #             "description": None,
    #             "vcpus": ,
    #             "hypervisor": None,
    #             "cpu_allocation": CpuAllocation....,
    #             "cpu_cores": None,
    #             "cpu_speed": None,
    #             "cpu_architecture": CpuArchitecture....,
    #             "cpu_manufacturer": None,
    #             "cpu_family": None,
    #             "cpu_model": None,
    #             "cpu_l1_cache: None,
    #             "cpu_l2_cache: None,
    #             "cpu_l3_cache: None,
    #             "cpu_flags: [],
    #             "cpus": [],
    #             "memory_amount": ,
    #             "memory_generation": None,
    #             "memory_speed": None,
    #             "memory_ecc": None,
    #             "gpu_count": 0,
    #             "gpu_memory_min": None,
    #             "gpu_memory_total": None,
    #             "gpu_manufacturer": None,
    #             "gpu_family": None,
    #             "gpu_model": None,
    #             "gpus": [],
    #             "storage_size": 0,
    #             "storage_type": None,
    #             "storages": [],
    #             "network_speed": None,
    #             "inbound_traffic": 0,
    #             "outbound_traffic": 0,
    #             "ipv4": 0,
    #         }
    #     )
    return items


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
