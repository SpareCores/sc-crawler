from concurrent.futures import ThreadPoolExecutor
from itertools import chain, repeat
from typing import Callable, List, Literal, Optional

from .table_fields import Status
from .tables import Region, Vendor


def fetch_servers(fn: Callable, where: str, vendor: Optional[Vendor]) -> List[dict]:
    """Fetch servers of a region/zone.

    Args:
        fn: A function that takes the region or zone id as its first and only argument.
            The returning list must conform with the Server object, or need to
            be in a format that [preprocess_servers][sc_crawler.vendor_helpers.preprocess_servers]'s
            `fn` can manage.
        where: A [Region][sc_crawler.tables.Region] or [Zone][sc_crawler.tables.Zone]
            `api_reference` or similar that is passed to `fn`.
        vendor: Optional [Vendor][sc_crawler.tables.Vendor] instance used for
            logging and progress bar updates.
    """
    servers = fn(where)
    if vendor:
        vendor.log(f"{len(servers)} server(s) found in {where}.")
    if vendor:
        vendor.progress_tracker.advance_task()
    return servers


def parallel_fetch_servers(
    vendor: Vendor, fn: Callable, id_col: str, by: Literal["regions", "zones"]
) -> List[dict]:
    """Fetch servers of all regions/zones in parallel on 8 threads.

    Args:
        vendor: Required [Vendor][sc_crawler.tables.Vendor] instance used for
            the regions lookup, logging and progress bar updates.
        fn: A function to be passed to [fetch_servers][sc_crawler.vendor_helpers.fetch_servers].
        id_cols: Field name to be used to deduplicate the list of server dicts.
        by: What objects of the `vendor` to iterate on.
    """

    locations = [
        i.api_reference for i in getattr(vendor, by) if i.status == Status.ACTIVE
    ]
    vendor.progress_tracker.start_task(
        name=f"Scanning {by} for server(s)", total=len(locations)
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        servers = executor.map(fetch_servers, repeat(fn), locations, repeat(vendor))
    servers = list(chain.from_iterable(servers))

    vendor.log(f"{len(servers)} server(s) found in {len(locations)} {by}.")
    servers = list({s[id_col]: s for s in servers}.values())
    vendor.log(f"{len(servers)} unique server(s) found.")
    active_servers = [
        s for s in servers if s.get("status", Status.ACTIVE) == Status.ACTIVE
    ]
    vendor.log(f"{len(active_servers)} ACTIVE server(s) found.")
    vendor.progress_tracker.hide_task()
    return servers


def preprocess_servers(servers: List[dict], vendor: Vendor, fn: Callable) -> List[dict]:
    """Preprocess servers before inserting into the database.

    Takes a list of dicts and tranform to a list of dicts that
    follows the [Server][sc_crawler.tables.Server] schema.

    Args:
        servers: To be passed to `fn`.
        vendor: The related [Vendor][sc_crawler.tables.Vendor] instance used
            for database connection, logging and progress bar updates.
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


def add_vendor_id(obj: dict, vendor: Vendor) -> dict:
    """Adds `vendor_id` field to a dict."""
    obj["vendor_id"] = vendor.vendor_id
    return obj


def get_region_by_id(region_id: str, vendor: Vendor) -> Optional[Region]:
    """Get a [region][sc_crawler.tables.Region] by its ID or alias.

    Args:
        region_id: The ID or alias of the region to get.
        vendor: The [vendor][sc_crawler.tables.Vendor] to get the region from.

    Returns:
        The [region][sc_crawler.tables.Region] if found, otherwise None.
    """
    return next(
        (
            region
            for region in vendor.regions
            if (region_id in [region.api_reference, *region.aliases])
        ),
        None,
    )
