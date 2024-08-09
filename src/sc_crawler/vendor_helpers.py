from typing import Callable, List, Optional


from .tables import Region, Vendor
from .table_fields import Status


def parallel_fetch_servers(
    region: Region, vendor: Optional[Vendor], fn: Callable
) -> List[dict]:
    """ """
    servers = []
    if region.status == Status.ACTIVE:
        servers = fn(region.region_id)
        vendor.log(f"{len(servers)} server(s) found in {region.region_id}.")
    vendor.progress_tracker.advance_task()
    return servers
