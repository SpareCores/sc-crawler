from concurrent.futures import ThreadPoolExecutor
from itertools import chain, repeat
from typing import Callable, List, Optional


from .tables import Region, Vendor
from .table_fields import Status


def fetch_servers(region: Region, vendor: Optional[Vendor], fn: Callable) -> List[dict]:
    """Fetch servers of a region.

    TODO"""
    servers = []
    if region.status == Status.ACTIVE:
        servers = fn(region.region_id)
        vendor.log(f"{len(servers)} server(s) found in {region.region_id}.")
    vendor.progress_tracker.advance_task()
    return servers


def parallel_fetch_servers(
    vendor: Optional[Vendor], fn: Callable, id_col: str
) -> List[dict]:
    """Fetch servers of regions in parallel on 8 threads.

    TODO"""
    vendor.progress_tracker.start_task(
        name="Scanning region(s) for server(s)", total=len(vendor.regions)
    )

    def search_servers(region: Region, vendor: Optional[Vendor]) -> List[dict]:
        return fetch_servers(region, vendor, fn)

    with ThreadPoolExecutor(max_workers=8) as executor:
        servers = executor.map(
            fetch_servers, vendor.regions, repeat(vendor), repeat(fn)
        )
    servers = list(chain.from_iterable(servers))

    vendor.log(f"{len(servers)} server(s) found in {len(vendor.regions)} regions.")
    servers = list({s[id_col]: s for s in servers}.values())
    vendor.log(f"{len(servers)} unique server(s) found.")
    vendor.progress_tracker.hide_task()
    return servers
