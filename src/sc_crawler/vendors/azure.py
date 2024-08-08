from typing import List
from os import environ

from azure.identity import DefaultAzureCredential
from azure.mgmt.resource import SubscriptionClient
from azure.mgmt.resource.subscriptions.v2022_12_01.models._models_py3 import Location
from cachier import cachier

from ..lookup import map_compliance_frameworks_to_vendor


credential = DefaultAzureCredential()
subscription_client = SubscriptionClient(credential)

# use first subcription if not passed via env var
subscription_id = environ.get(
    "AZURE_SUBSCRIPTION_ID",
    default=next(subscription_client.subscriptions.list()).subscription_id,
)

# ##############################################################################
# Cached Azure client wrappers


@cachier()
def _regions() -> List[Location]:
    locations = []
    for location in subscription_client.subscriptions.list_locations(subscription_id):
        locations.append(location.as_dict())
    return locations


# ##############################################################################
# Public methods to fetch data


def inventory_compliance_frameworks(vendor):
    """Manual list of known compliance frameworks at Azure.

    Data collected from <https://learn.microsoft.com/en-us/azure/compliance/>."""
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id, ["hipaa", "soc2t2", "iso27001"]
    )


def inventory_regions(vendor):
    """List all regions via API call."""
    items = []
    for region in _regions():
        if region["metadata"]["region_type"] == "Physical":
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region["name"],
                    "name": region["display_name"],
                    "api_reference": region["name"],
                    "display_name": (
                        region["display_name"]
                        + " ("
                        + region["metadata"]["geography_group"]  # TODO
                        + ")"
                    ),
                    "country_id": region["metadata"]["geography_group"],  # TODO
                    "state": None,
                    "city": region["metadata"]["physical_location"],  # TODO
                    "address_line": None,
                    "zip_code": None,
                    "lat": region["metadata"]["latitude"],
                    "lon": region["metadata"]["longitude"],
                    "founding_year": None,  # TODO
                    "green_energy": False,  # TODO
                }
            )
    return items


def inventory_zones(vendor):
    items = []
    # for zone in []:
    #     items.append({
    #         "vendor_id": vendor.vendor_id,
    #         "datacenter_id": "",
    #         "zone_id": "",
    #         "name": "",
    #     })
    return items


def inventory_servers(vendor):
    # items = []
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
    # items = []
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
