import os
from functools import cache

from hcloud import Client

from ..lookup import map_compliance_frameworks_to_vendor
from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)
from ..utils import scmodels_to_dict

# ##############################################################################
# Cached client wrappers


@cache
def _client() -> Client:
    """Authorized Hetzner Cloud client using the HCLOUD_TOKEN env var."""
    try:
        token = os.environ["HCLOUD_TOKEN"]
    except KeyError:
        raise KeyError("Missing environment variable: HCLOUD_TOKEN")
    return Client(token=token)


# not caching actual client calls, as the API returns highly recursive
# and often cyclic objects that is not compatible with cachier/pickle

# ##############################################################################
# Internal helpers


def _server_cpu(server_name):
    """Manual mapping of CPU info for server types.

    Source: <https://www.hetzner.com/cloud/>
    """
    # not trying to rely on product line name patterns, as might change,
    # so rather providing a full list of known entities, and fail on unknown
    if server_name.upper() in ["CX11", "CX21", "CX31", "CX41", "CX51"]:
        return ("Intel", "Xeon Gold", None)
    if server_name.upper() in ["CPX11", "CPX21", "CPX31", "CPX41", "CPX51"]:
        return ("AMD", "EPYC 7002", None)
    if server_name.upper() in ["CAX11", "CAX21", "CAX31", "CAX41"]:
        return ("AMD", "Ampere Altra", None)
    if server_name.upper() in ["CCX13", "CCX23", "CCX33", "CCX43", "CCX53", "CCX63"]:
        return ("AMD", None, None)
    raise ValueError("Unknown Hetzner Cloud server name: " + server_name)


# ##############################################################################
# Public methods to fetch data


def inventory_compliance_frameworks(vendor):
    """Manual list of known compliance frameworks at Hetzner.

    Data collected from <https://www.hetzner.com/unternehmen/zertifizierung>."""
    return map_compliance_frameworks_to_vendor(vendor.vendor_id, ["iso27001"])


def inventory_datacenters(vendor):
    """List all datacenters via API call.

    Hetzner Cloud uses integers for the datacenter id that we
    convert into string. Best to use the unique `name`, which
    can be also passed instead of the `id` in most `hcloud`
    API endpoints via the `id_or_name` method.

    Not taking the Hetzner unique `name` as id, as it's not
    stated to be unique for other resources, and uniqueness
    for servers might also change in the future.

    All datacenters are powered by green energy as per
    <https://www.hetzner.com/unternehmen/umweltschutz/>.

    Lon/lat coordinates were collected by searching for Hetzner
    locations in the Datacenter's city.

    """
    datacenters = {
        "2": {  # Nuremberg
            "lat": 49.4498349,
            "lon": 11.0128772,
        },
        "3": {  # Helsinki
            "lat": 60.3433291,
            "lon": 25.02683,
        },
        "4": {  # Falkenstein
            "lat": 50.4793313,
            "lon": 12.3331105,
        },
        "5": {  # Ashburn, VA
            "lat": 39.0176685,
            "lon": -77.468102,
        },
        "6": {  # Hillsboro, OR
            "lat": 45.558319,
            "lon": -122.9306602,
        },
    }

    items = []
    for datacenter in _client().datacenters.get_all():
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": str(datacenter.id),
                "name": datacenter.name,
                "api_reference": datacenter.name,
                "display_name": (
                    datacenter.location.city + f" ({datacenter.location.country})"
                ),
                # TODO add datacenter.description
                "aliases": [datacenter.location.name],
                "country_id": datacenter.location.country,
                "state": None,
                "city": datacenter.location.city,
                "address_line": None,
                "zip_code": None,
                "lat": datacenters[str(datacenter.id)]["lat"],
                "lon": datacenters[str(datacenter.id)]["lon"],
                "founding_year": None,
                "green_energy": True,
            }
        )
    return items


def inventory_zones(vendor):
    """List all datacenters as availability zones.

    There is no concept of having multiple availability zones withing
    a datacenter at Hetzner Cloud, so creating 1-1 dummy Zones reusing
    the Datacenter id and name.
    """
    items = []
    for datacenter in vendor.datacenters:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": datacenter.datacenter_id,
                "zone_id": datacenter.datacenter_id,
                "name": datacenter.name,
                "api_reference": datacenter.name,
                "display_name": datacenter.name,
            }
        )
    return items


def inventory_servers(vendor):
    """List all server types from API and manual data entry from the Hetzner Cloud homepage.

    CPU information is recorded from <https://www.hetzner.com/cloud/> as not exposed via API."""
    items = []
    for server in _client().server_types.get_all():
        # CPU info not available via the API,
        # collected from https://www.hetzner.com/cloud/
        cpu = _server_cpu(server.name)
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "server_id": str(server.id),
                "name": server.name,
                "api_reference": server.name,
                "display_name": server.name,
                "description": server.description,
                "family": server.name.rstrip("0123456789"),
                "vcpus": server.cores,
                "hypervisor": None,
                "cpu_allocation": (
                    CpuAllocation.SHARED
                    if server.cpu_type == "shared"
                    else CpuAllocation.DEDICATED
                ),
                "cpu_cores": None,
                "cpu_speed": None,
                "cpu_architecture": (
                    CpuArchitecture.ARM64
                    if server.architecture == "arm"
                    else CpuArchitecture.X86_64
                ),
                "cpu_manufacturer": cpu[0],
                "cpu_family": cpu[1],
                "cpu_model": cpu[2],
                "cpus": [],
                "memory": server.memory * 1024,
                "gpu_count": 0,
                "gpu_memory_min": None,
                "gpu_memory_total": None,
                "gpu_manufacturer": None,
                "gpu_model": None,
                "gpus": [],
                "storage_size": server.disk,
                "storage_type": (
                    StorageType.SSD
                    if server.storage_type == "local"
                    else StorageType.NETWORK
                ),
                "storages": [],
                "network_speed": None,
                # https://docs.hetzner.com/cloud/billing/faq/#how-do-you-bill-for-traffic
                "inbound_traffic": 0,  # free
                "outbound_traffic": server.included_traffic / (1024**3),
                "ipv4": 0,
                "status": Status.ACTIVE if not server.deprecation else Status.INACTIVE,
            }
        )
    return items


def inventory_server_prices(vendor):
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name", "aliases"])
    items = []
    for server in _client().server_types.get_all():
        for location in server.prices:
            datacenter_id = datacenters[location["location"]].datacenter_id
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "datacenter_id": datacenter_id,
                    # zone_id is a dummy datacenter_id as there are no zones at Hetzner
                    "zone_id": datacenter_id,
                    "server_id": str(server.id),
                    "operating_system": "Linux",
                    "allocation": Allocation.ONDEMAND,
                    "unit": PriceUnit.HOUR,
                    "price": float(location["price_hourly"]["net"]),
                    "price_upfront": 0,
                    "price_tiered": [],
                    "currency": "EUR",
                }
            )
    return items


def inventory_server_prices_spot(vendor):
    """There are no spot instaces at Hetzner."""
    return []


def inventory_storages(vendor):
    """Block storage volume information collected manually.

    There is not information shared vie the API, so information
    was collected manually from:

    - <https://www.hetzner.com/cloud/>
    - <https://docs.hetzner.cloud/#volumes-create-a-volume>
    """
    items = [
        {
            "storage_id": "block",
            "vendor_id": vendor.vendor_id,
            "name": "Block storage volume",
            "description": None,
            "storage_type": StorageType.NETWORK,
            "max_iops": None,
            "max_throughput": None,
            "min_size": 10,
            "max_size": 10240,
        }
    ]
    return items


def inventory_storage_prices(vendor):
    """Block storage volume pricing information collected manually.

    Source: <https://www.hetzner.com/cloud/>
    """
    items = []
    for datacenter in vendor.datacenters:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": datacenter.datacenter_id,
                "storage_id": "block",
                "unit": PriceUnit.GB_MONTH,
                "price": 0.0440,
                "currency": "EUR",
            }
        )
    return items


def inventory_traffic_prices(vendor):
    """Traffic price collected manually.

    Source: <https://docs.hetzner.com/robot/general/traffic/>
    """
    items = []
    for datacenter in vendor.datacenters:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": datacenter.datacenter_id,
                "price": 0,
                "price_tiered": [],
                "currency": "EUR",
                "unit": PriceUnit.GB_MONTH,
                "direction": TrafficDirection.IN,
            }
        )
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": datacenter.datacenter_id,
                "price": round(1 / 1024, 8),
                "price_tiered": [],
                "currency": "EUR",
                "unit": PriceUnit.GB_MONTH,
                "direction": TrafficDirection.OUT,
            }
        )
    return items


def inventory_ipv4_prices(vendor):
    """IPv4 price collected manually.

    Source: <https://docs.hetzner.com/general/others/ipv4-pricing/#cloud>
    """
    items = []
    for datacenter in vendor.datacenters:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": datacenter.datacenter_id,
                "price": 0.50,
                "currency": "EUR",
                "unit": PriceUnit.MONTH,
            }
        )
    return items
