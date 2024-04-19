from functools import cache
from typing import List

from cachier import cachier, get_default_params
from google.auth import default
from google.cloud import compute_v1
from ..lookup import map_compliance_frameworks_to_vendor


# ##############################################################################
# Cached gcp client wrappers


@cache
def _project_id() -> str:
    """Returns the project id for the curent user as per Application Default Credentials."""
    return default()[1]


@cachier()
def _regions() -> List[compute_v1.types.compute.Region]:
    client = compute_v1.RegionsClient()
    pager = client.list(project=_project_id())
    items = []
    for page in pager.pages:
        for item in page.items:
            items.append(item)
    return items


# ##############################################################################
# Internal helpers


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
    - location: <https://cloud.google.com/compute/docs/regions-zones#available>
    - energy carbon data: <https://cloud.google.com/sustainability/region-carbon#data>
    - launch dates were collected from GCP blog posts, such as <https://cloud.google.com/blog/products/infrastructure/introducing-new-google-cloud-regions>
    """
    regions = _regions()
    items = []
    for region in regions:
        # TODO lookup location + green energy from https://cloud.google.com/compute/docs/regions-zones#available
        # https://cloud.google.com/sustainability/region-carbon#data
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": region.id,
                "name": region.name,
                "aliases": [],
                "country_id": "",
                "state": None,
                "city": None,
                "address_line": None,
                "zip_code": None,
                "founding_year": None,
                "green_energy": None,
            }
        )
    return items


def inventory_zones(vendor):
    return []


def inventory_servers(vendor):
    return []


def inventory_server_prices(vendor):
    return []


def inventory_server_prices_spot(vendor):
    return []


def inventory_storages(vendor):
    return []


def inventory_storage_prices(vendor):
    return []


def inventory_traffic_prices(vendor):
    return []


def inventory_ipv4_prices(vendor):
    return []
