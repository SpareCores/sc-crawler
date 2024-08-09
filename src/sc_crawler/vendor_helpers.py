from concurrent.futures import ThreadPoolExecutor
from itertools import chain, repeat
from typing import Callable, List, Optional


from .tables import Region, Vendor
from .table_fields import Status


def fetch_servers(region: Region, vendor: Optional[Vendor], fn: Callable) -> List[dict]:
    """Fetch servers of a region.

    Args:
        region: A Region object with `region_id` that is passed to `fn`.
        vendor: Optional Vendor instance used for logging and progress bar updates.
        fn: A function that takes the region id as its first and only argument.
            The returning list must conform with the Server object, or need to
            be in a format that [preprocess_servers][sc_crawler.vendor_helpers.preprocess_servers]'s
            `fn` can manage.
    """
    servers = []
    if region.status == Status.ACTIVE:
        servers = fn(region.region_id)
        if vendor:
            vendor.log(f"{len(servers)} server(s) found in {region.region_id}.")
    if vendor:
        vendor.progress_tracker.advance_task()
    return servers


def parallel_fetch_servers(vendor: Vendor, fn: Callable, id_col: str) -> List[dict]:
    """Fetch servers from all regions in parallel on 8 threads.

    Args:
        vendor: Required Vendor instance used for the regions lookup, logging and progress bar updates.
        fn: A function to be passed to [fetch_servers][sc_crawler.vendor_helpers.fetch_servers].
        id_cols: Field name to be used to deduplicate the list of server dicts.
    """
    vendor.progress_tracker.start_task(
        name="Scanning region(s) for server(s)", total=len(vendor.regions)
    )

    def search_servers(region: Region, vendor: Vendor) -> List[dict]:
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


def preprocess_servers(servers: List[dict], vendor: Vendor, fn: Callable) -> List[dict]:
    """Preprocess servers before inserting into the database.

    Takes a list of dicts and tranform to a list of dicts that
    follows the [Server][sc_crawler.tables.Server] schema.

    Args:
        servers: To be passed to `fn`.
        vendor: The related Vendor instance used for database connection, logging and progress bar updates.
        fn: A function that takes a server from `servers` (one-by-one) and the `vendor`.
    """
    vendor.progress_tracker.start_task(
        name="Preprocessing server(s)", total=len(servers)
    )
    processed = []
    for server in servers:
        processed.append(fn(server, vendor))
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return processed
