"""Inventory of Oracle Cloud Infrastructure via its API and the public price list: servers, storages, traffic and IPv4 addresses, with their prices."""

from functools import cache
from os import environ, getenv
from typing import Any

import oci
from cachier import cachier

from ..logger import logger
from ..lookup import map_compliance_frameworks_to_vendor
from ..sentry import sentry_capture_or_raise
from ..table_fields import Status

# Curated location of the commercial (OC1 realm) regions, as the API only returns
# the region identifier and key. Names, cities and countries are from
# <https://docs.oracle.com/en-us/iaas/Content/General/Concepts/regions.htm>,
# coordinates are city-level.
_REGION_LOCATIONS: dict[str, dict] = {
    "af-casablanca-1": {
        "name": "Morocco West (Casablanca)",
        "country_id": "MA",
        "city": "Casablanca",
        "lat": 33.5731,
        "lon": -7.5898,
    },
    "af-johannesburg-1": {
        "name": "South Africa Central (Johannesburg)",
        "country_id": "ZA",
        "city": "Johannesburg",
        "lat": -26.2041,
        "lon": 28.0473,
    },
    "ap-batam-1": {
        "name": "Indonesia North (Batam)",
        "country_id": "ID",
        "city": "Batam",
        "lat": 1.0456,
        "lon": 104.0305,
    },
    "ap-chuncheon-1": {
        "name": "South Korea North (Chuncheon)",
        "country_id": "KR",
        "city": "Chuncheon",
        "lat": 37.8813,
        "lon": 127.7298,
    },
    "ap-hyderabad-1": {
        "name": "India South (Hyderabad)",
        "country_id": "IN",
        "state": "Telangana",
        "city": "Hyderabad",
        "lat": 17.3850,
        "lon": 78.4867,
    },
    "ap-kulai-2": {
        "name": "Malaysia West 2 (Kulai)",
        "country_id": "MY",
        "state": "Johor",
        "city": "Kulai",
        "lat": 1.6561,
        "lon": 103.6032,
    },
    "ap-melbourne-1": {
        "name": "Australia Southeast (Melbourne)",
        "country_id": "AU",
        "state": "Victoria",
        "city": "Melbourne",
        "lat": -37.8136,
        "lon": 144.9631,
    },
    "ap-mumbai-1": {
        "name": "India West (Mumbai)",
        "country_id": "IN",
        "state": "Maharashtra",
        "city": "Mumbai",
        "lat": 19.0760,
        "lon": 72.8777,
    },
    "ap-osaka-1": {
        "name": "Japan Central (Osaka)",
        "country_id": "JP",
        "city": "Osaka",
        "lat": 34.6937,
        "lon": 135.5023,
    },
    "ap-seoul-1": {
        "name": "South Korea Central (Seoul)",
        "country_id": "KR",
        "city": "Seoul",
        "lat": 37.5665,
        "lon": 126.9780,
    },
    "ap-singapore-1": {
        "name": "Singapore (Singapore)",
        "country_id": "SG",
        "city": "Singapore",
        "lat": 1.3521,
        "lon": 103.8198,
    },
    "ap-singapore-2": {
        "name": "Singapore West (Singapore)",
        "country_id": "SG",
        "city": "Singapore",
        "lat": 1.3521,
        "lon": 103.8198,
    },
    "ap-sydney-1": {
        "name": "Australia East (Sydney)",
        "country_id": "AU",
        "state": "New South Wales",
        "city": "Sydney",
        "lat": -33.8688,
        "lon": 151.2093,
    },
    "ap-tokyo-1": {
        "name": "Japan East (Tokyo)",
        "country_id": "JP",
        "city": "Tokyo",
        "lat": 35.6762,
        "lon": 139.6503,
    },
    "ca-montreal-1": {
        "name": "Canada Southeast (Montreal)",
        "country_id": "CA",
        "state": "Quebec",
        "city": "Montreal",
        "lat": 45.5019,
        "lon": -73.5674,
    },
    "ca-toronto-1": {
        "name": "Canada Southeast (Toronto)",
        "country_id": "CA",
        "state": "Ontario",
        "city": "Toronto",
        "lat": 43.6532,
        "lon": -79.3832,
    },
    "eu-amsterdam-1": {
        "name": "Netherlands Northwest (Amsterdam)",
        "country_id": "NL",
        "city": "Amsterdam",
        "lat": 52.3676,
        "lon": 4.9041,
    },
    "eu-frankfurt-1": {
        "name": "Germany Central (Frankfurt)",
        "country_id": "DE",
        "state": "Hesse",
        "city": "Frankfurt",
        "lat": 50.1109,
        "lon": 8.6821,
    },
    "eu-madrid-1": {
        "name": "Spain Central (Madrid)",
        "country_id": "ES",
        "city": "Madrid",
        "lat": 40.4168,
        "lon": -3.7038,
    },
    "eu-madrid-3": {
        "name": "Spain Central (Madrid 3)",
        "country_id": "ES",
        "city": "Madrid",
        "lat": 40.4168,
        "lon": -3.7038,
    },
    "eu-marseille-1": {
        "name": "France South (Marseille)",
        "country_id": "FR",
        "city": "Marseille",
        "lat": 43.2965,
        "lon": 5.3698,
    },
    "eu-milan-1": {
        "name": "Italy Northwest (Milan)",
        "country_id": "IT",
        "city": "Milan",
        "lat": 45.4642,
        "lon": 9.1900,
    },
    "eu-paris-1": {
        "name": "France Central (Paris)",
        "country_id": "FR",
        "city": "Paris",
        "lat": 48.8566,
        "lon": 2.3522,
    },
    "eu-stockholm-1": {
        "name": "Sweden Central (Stockholm)",
        "country_id": "SE",
        "city": "Stockholm",
        "lat": 59.3293,
        "lon": 18.0686,
    },
    "eu-turin-1": {
        "name": "Italy North (Turin)",
        "country_id": "IT",
        "city": "Turin",
        "lat": 45.0703,
        "lon": 7.6869,
    },
    "eu-zurich-1": {
        "name": "Switzerland North (Zurich)",
        "country_id": "CH",
        "city": "Zurich",
        "lat": 47.3769,
        "lon": 8.5417,
    },
    "il-jerusalem-1": {
        "name": "Israel Central (Jerusalem)",
        "country_id": "IL",
        "city": "Jerusalem",
        "lat": 31.7683,
        "lon": 35.2137,
    },
    "me-abudhabi-1": {
        "name": "UAE Central (Abu Dhabi)",
        "country_id": "AE",
        "city": "Abu Dhabi",
        "lat": 24.4539,
        "lon": 54.3773,
    },
    "me-dubai-1": {
        "name": "UAE East (Dubai)",
        "country_id": "AE",
        "city": "Dubai",
        "lat": 25.2048,
        "lon": 55.2708,
    },
    "me-jeddah-1": {
        "name": "Saudi Arabia West (Jeddah)",
        "country_id": "SA",
        "city": "Jeddah",
        "lat": 21.4858,
        "lon": 39.1925,
    },
    "me-riyadh-1": {
        "name": "Saudi Arabia Central (Riyadh)",
        "country_id": "SA",
        "city": "Riyadh",
        "lat": 24.7136,
        "lon": 46.6753,
    },
    "mx-monterrey-1": {
        "name": "Mexico Northeast (Monterrey)",
        "country_id": "MX",
        "state": "Nuevo León",
        "city": "Monterrey",
        "lat": 25.6866,
        "lon": -100.3161,
    },
    "mx-queretaro-1": {
        "name": "Mexico Central (Queretaro)",
        "country_id": "MX",
        "state": "Querétaro",
        "city": "Queretaro",
        "lat": 20.5888,
        "lon": -100.3899,
    },
    "sa-bogota-1": {
        "name": "Colombia Central (Bogota)",
        "country_id": "CO",
        "city": "Bogota",
        "lat": 4.7110,
        "lon": -74.0721,
    },
    "sa-santiago-1": {
        "name": "Chile Central (Santiago)",
        "country_id": "CL",
        "city": "Santiago",
        "lat": -33.4489,
        "lon": -70.6693,
    },
    "sa-saopaulo-1": {
        "name": "Brazil East (Sao Paulo)",
        "country_id": "BR",
        "state": "São Paulo",
        "city": "Sao Paulo",
        "lat": -23.5505,
        "lon": -46.6333,
    },
    "sa-valparaiso-1": {
        "name": "Chile West (Valparaiso)",
        "country_id": "CL",
        "city": "Valparaiso",
        "lat": -33.0472,
        "lon": -71.6127,
    },
    "sa-vinhedo-1": {
        "name": "Brazil Southeast (Vinhedo)",
        "country_id": "BR",
        "state": "São Paulo",
        "city": "Vinhedo",
        "lat": -23.0297,
        "lon": -46.9753,
    },
    "uk-cardiff-1": {
        "name": "UK West (Newport)",
        "country_id": "GB",
        "state": "Wales",
        "city": "Newport",
        "lat": 51.5842,
        "lon": -2.9977,
    },
    "uk-london-1": {
        "name": "UK South (London)",
        "country_id": "GB",
        "state": "England",
        "city": "London",
        "lat": 51.5074,
        "lon": -0.1278,
    },
    "us-ashburn-1": {
        "name": "US East (Ashburn)",
        "country_id": "US",
        "state": "Virginia",
        "city": "Ashburn",
        "lat": 39.0438,
        "lon": -77.4874,
    },
    "us-chicago-1": {
        "name": "US Midwest (Chicago)",
        "country_id": "US",
        "state": "Illinois",
        "city": "Chicago",
        "lat": 41.8781,
        "lon": -87.6298,
    },
    "us-phoenix-1": {
        "name": "US West (Phoenix)",
        "country_id": "US",
        "state": "Arizona",
        "city": "Phoenix",
        "lat": 33.4484,
        "lon": -112.0740,
    },
    "us-sanjose-1": {
        "name": "US West (San Jose)",
        "country_id": "US",
        "state": "California",
        "city": "San Jose",
        "lat": 37.3382,
        "lon": -121.8863,
    },
}


@cache
def _config() -> dict:
    """Build the OCI SDK configuration for API key based authentication.

    Environment variables are preferred (all required when `OCI_TENANCY_OCID`
    is set):

    - `OCI_USER_OCID`
    - `OCI_TENANCY_OCID`
    - `OCI_FINGERPRINT`
    - `OCI_REGION`: the home region of the tenancy (e.g. eu-frankfurt-1)
    - `OCI_PRIVATE_KEY` (PEM content) or `OCI_PRIVATE_KEY_PATH`

    Otherwise falling back to the standard `~/.oci/config` file, using the
    profile set in `OCI_CONFIG_PROFILE` (`DEFAULT` if not set).
    """
    if "OCI_TENANCY_OCID" not in environ:
        return oci.config.from_file(
            profile_name=getenv("OCI_CONFIG_PROFILE", oci.config.DEFAULT_PROFILE)
        )
    for ev in ["OCI_USER_OCID", "OCI_FINGERPRINT", "OCI_REGION"]:
        if ev not in environ:
            raise KeyError(f"Missing environment variable: {ev}")
    config = {
        "user": environ["OCI_USER_OCID"],
        "tenancy": environ["OCI_TENANCY_OCID"],
        "fingerprint": environ["OCI_FINGERPRINT"],
        "region": environ["OCI_REGION"],
    }
    if "OCI_PRIVATE_KEY" in environ:
        config["key_content"] = environ["OCI_PRIVATE_KEY"]
    elif "OCI_PRIVATE_KEY_PATH" in environ:
        config["key_file"] = environ["OCI_PRIVATE_KEY_PATH"]
    else:
        raise KeyError(
            "Missing environment variable: OCI_PRIVATE_KEY or OCI_PRIVATE_KEY_PATH"
        )
    oci.config.validate_config(config)
    return config


@cache
def _client(client_class: type, region: str | None = None) -> Any:
    """Create an OCI SDK client in a region, defaulting to the home region."""
    config = _config()
    if region:
        config = config | {"region": region}
    return client_class(config, retry_strategy=oci.retry.DEFAULT_RETRY_STRATEGY)


@cachier()
def _get_regions() -> list[dict]:
    """List all regions of the realm (ListRegions).

    Reference: <https://docs.oracle.com/en-us/iaas/api/#/en/identity/20160918/Region/ListRegions>
    """
    # example response (after `oci.util.to_dict`):
    # [
    #     {'key': 'AMS', 'name': 'eu-amsterdam-1'},
    #     {'key': 'ARN', 'name': 'eu-stockholm-1'},
    #     # ...
    # ]
    regions = _client(oci.identity.IdentityClient).list_regions().data
    return oci.util.to_dict(regions)


@cachier()
def _get_region_subscriptions() -> list[dict]:
    """List the regions the tenancy is subscribed to (ListRegionSubscriptions).

    Reference: <https://docs.oracle.com/en-us/iaas/api/#/en/identity/20160918/RegionSubscription/ListRegionSubscriptions>
    """
    # example response (after `oci.util.to_dict`):
    # [
    #     {
    #         'region_key': 'FRA',
    #         'region_name': 'eu-frankfurt-1',
    #         'status': 'READY',
    #         'is_home_region': True,
    #     },
    #     # ...
    # ]
    subscriptions = (
        _client(oci.identity.IdentityClient)
        .list_region_subscriptions(_config()["tenancy"])
        .data
    )
    return oci.util.to_dict(subscriptions)


@cachier(separate_files=True)
def _get_availability_domains(region: str) -> list[str]:
    """List the availability domain names of a region (ListAvailabilityDomains).

    The names are specific to the tenancy, both the prefix and the mapping of
    the numbers to datacenters, e.g. `Uocm:EU-FRANKFURT-1-AD-1` or `Uocm:PHX-AD-1`.

    Reference: <https://docs.oracle.com/en-us/iaas/api/#/en/identity/20160918/AvailabilityDomain/ListAvailabilityDomains>
    """
    # example response (after `oci.util.to_dict`):
    # [
    #     {
    #         'name': 'Uocm:EU-FRANKFURT-1-AD-1',
    #         'id': 'ocid1.availabilitydomain.oc1..aaaa...',
    #         'compartment_id': 'ocid1.tenancy.oc1..aaaa...',
    #     },
    #     # ...
    # ]
    availability_domains = (
        _client(oci.identity.IdentityClient, region)
        .list_availability_domains(_config()["tenancy"])
        .data
    )
    return [availability_domain.name for availability_domain in availability_domains]


def _zone_id(region: str, availability_domain: str) -> str:
    """Zone id from the region and the tenancy-specific availability domain name.

    E.g. `Uocm:EU-FRANKFURT-1-AD-2` in eu-frankfurt-1 -> `eu-frankfurt-1-ad-2`
    and `Uocm:PHX-AD-1` in us-phoenix-1 -> `us-phoenix-1-ad-1`.
    """
    number = availability_domain.rsplit("-", 1)[-1]
    if not number.isdigit():
        raise ValueError(f"Unknown availability domain name: {availability_domain}")
    return f"{region}-ad-{number}"


def inventory_compliance_frameworks(vendor):
    """Manual list of known compliance frameworks at Oracle Cloud Infrastructure.

    Data sources:

    - <https://www.oracle.com/corporate/cloud-compliance/>
    - <https://blogs.oracle.com/cloud-infrastructure/fall-2022-compliance-attestations>
    """
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id,
        [
            "hipaa",
            "soc2t2",
            "iso27001",
        ],
    )


def inventory_regions(vendor):
    """List all regions of the commercial realm.

    The API returns the identifier and key of the regions only, so the
    location is looked up from a manual mapping based on
    <https://docs.oracle.com/en-us/iaas/Content/General/Concepts/regions.htm>.

    Availability domains and shapes can be listed only in the regions the
    tenancy is subscribed to, so the other regions are stored as INACTIVE.
    """
    items = []
    subscribed = {
        subscription["region_name"]
        for subscription in _get_region_subscriptions()
        if subscription["status"] == "READY"
    }
    not_subscribed = []
    for region in _get_regions():
        with sentry_capture_or_raise(vendor=vendor):
            region_id = region["name"]
            if region_id not in _REGION_LOCATIONS:
                raise KeyError(f"Unknown OCI region without location: {region_id}")
            location = _REGION_LOCATIONS[region_id]
            if region_id not in subscribed:
                not_subscribed.append(region_id)
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region_id,
                    "name": location["name"],
                    "api_reference": region_id,
                    "display_name": location["name"],
                    "aliases": [region["key"]],
                    "country_id": location["country_id"],
                    "state": location.get("state"),
                    "city": location["city"],
                    "address_line": None,
                    "zip_code": None,
                    "lon": location["lon"],
                    "lat": location["lat"],
                    "founding_year": location.get("founding_year"),
                    "green_energy": location.get("green_energy"),
                    "status": (
                        Status.ACTIVE if region_id in subscribed else Status.INACTIVE
                    ),
                }
            )
    if not_subscribed:
        logger.warning(
            f"The OCI tenancy is not subscribed to {len(not_subscribed)} regions "
            f"(e.g. {', '.join(not_subscribed[:5])}), storing those as inactive "
            "without zones and servers."
        )
    return items


def inventory_zones(vendor):
    """List the availability domains of the subscribed regions as zones.

    The availability domain names (e.g. `Uocm:EU-FRANKFURT-1-AD-1`) are specific
    to the tenancy, so the zone id is built from the region and the number of
    the availability domain, and the full name is kept as the API reference.
    Note that the numbers are also mapped to the datacenters per tenancy, so
    e.g. AD-1 can be a different datacenter in another tenancy.

    Fault domains are not listed as zones.
    """
    items = []
    regions = [region for region in vendor.regions if region.status == Status.ACTIVE]
    vendor.progress_tracker.start_task(name="Fetching zones", total=len(regions))
    for region in regions:
        for availability_domain in _get_availability_domains(region.api_reference):
            display_name = availability_domain.split(":")[-1]
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "zone_id": _zone_id(region.region_id, availability_domain),
                    "name": display_name,
                    "api_reference": availability_domain,
                    "display_name": display_name,
                }
            )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return items


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


# TODO: Implement database collectors (OCI Database with PostgreSQL)


def inventory_databases(vendor):
    return []


def inventory_database_prices(vendor):
    return []


def inventory_database_storages(vendor):
    return []


def inventory_database_storage_prices(vendor):
    return []
