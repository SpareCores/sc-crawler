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
