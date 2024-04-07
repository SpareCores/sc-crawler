import os

from hcloud import Client

# TODO late load
client = Client(token=os.environ["HCLOUD_TOKEN"])


def inventory_compliance_frameworks(vendor):
    """Manual list of known compliance frameworks at Hetzner.

    Data collected from <https://www.hetzner.com/unternehmen/zertifizierung>."""
    ## TODO refactor to helper
    compliance_frameworks = ["iso27001"]
    items = []
    for compliance_framework in compliance_frameworks:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "compliance_framework_id": compliance_framework,
            }
        )
    return items


def inventory_datacenters(vendor):
    """List all datacenters via API call.

    Hetzner Cloud uses integers for the datacenter id that we
    convereted into strings, and the datacenter name is stored as an
    alias.

    All datacenters are powered by green energy as per
    <https://www.hetzner.com/unternehmen/umweltschutz/>.
    """
    items = []
    for datacenter in client.datacenters.get_all():
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": str(datacenter.id),
                "name": datacenter.name,
                # TODO add datacenter.description
                "aliases": [],
                "country_id": datacenter.location.country,
                "state": None,
                "city": datacenter.location.city,
                "address_line": None,
                "zip_code": None,
                "founding_year": None,
                "green_energy": True,
            }
        )
    return items


def inventory_zones(vendor):
    """List all datacenters as availability zones.

    There is no concept of having multiple availability zones withing
    a datacenter at Hetzner Cloud, so creating 1-1 dummy Zones.
    """
    items = []
    for datacenter in vendor.datacenters:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": datacenter.datacenter_id,
                "zone_id": datacenter.datacenter_id,
                "name": datacenter.name,
            }
        )
    return items


def inventory_servers(vendor):
    # https://hcloud-python.readthedocs.io/en/stable/api.clients.server_types.html#hcloud.server_types.client.ServerTypesClient
    # https://hcloud-python.readthedocs.io/en/stable/api.clients.servers.html#hcloud.servers.client.ServersClient.get_all
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
