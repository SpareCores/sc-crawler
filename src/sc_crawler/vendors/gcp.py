from functools import cache
from typing import List

from cachier import cachier
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
            "datacenter_id": region.id,
            "name": region.name,
        }
        for k, v in manual_data[region.name].items():
            item[k] = v
        items.append(item)
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
