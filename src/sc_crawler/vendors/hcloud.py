from datetime import timedelta
import os

from functools import cache
from hcloud import Client

from ..lookup import map_compliance_frameworks_to_vendor
from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    Disk,
    Gpu,
    PriceTier,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)

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
    convereted into strings, and the datacenter name is stored as an
    alias.

    All datacenters are powered by green energy as per
    <https://www.hetzner.com/unternehmen/umweltschutz/>.
    """
    items = []
    for datacenter in _client().datacenters.get_all():
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
            }
        )
    return items


def inventory_servers(vendor):
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
                # TODO add server.description
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
