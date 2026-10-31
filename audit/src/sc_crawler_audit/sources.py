"""Load the list of official vendor pages and resolve the pages of an audit run."""

import json
import re
from pathlib import Path
from typing import Iterator, List, Optional, Tuple
from urllib.parse import urlparse

import yaml

from . import PROJECT_ROOT
from .schema import SourcePage, Sources, VendorSources

DEFAULT_SOURCES = PROJECT_ROOT / "sources.yaml"


def load_sources(path: Optional[Path] = None) -> Sources:
    """Parse and validate the sources YAML file (defaults to the bundled one)."""
    text = Path(path).read_text() if path else DEFAULT_SOURCES.read_text()
    sources = Sources.model_validate(yaml.safe_load(text))
    for vendor_id, vendor in sources.vendors.items():
        ids = [p.id for p in vendor.pages]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"Duplicate page ids for {vendor_id}: {dupes}")
        for page in vendor.pages:
            if not is_allowed(page.url, vendor.allowed_domains):
                raise ValueError(
                    f"{vendor_id}/{page.id} URL is outside allowed domains: {page.url}"
                )
            if page.covers:
                re.compile(page.covers)
    return sources


def is_allowed(url: str, allowed_domains: List[str]) -> bool:
    """Check if the host of an URL is one of the domains or their subdomains."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


def page_slug(page_id: str) -> str:
    """File-system safe version of a page id."""
    return re.sub(r"[^A-Za-z0-9._-]+", "__", page_id)


def pages_dir(out_dir: Path, vendor_id: str) -> Path:
    return Path(out_dir) / "pages" / vendor_id


def extracted_dir(out_dir: Path, vendor_id: str) -> Path:
    return Path(out_dir) / "extracted" / vendor_id


def discovered_path(out_dir: Path, vendor_id: str) -> Path:
    return pages_dir(out_dir, vendor_id) / "_discovered.json"


def child_page(parent: SourcePage, url: str) -> SourcePage:
    """Build a page definition for a link discovered on a `follow` page."""
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1] or "index"
    query = urlparse(url).query
    if query:
        slug += "-" + query
    return SourcePage(
        id=f"{parent.id}/{slug}",
        url=url,
        kinds=parent.follow.kinds,
        covers=parent.follow.covers,
        complete=parent.follow.complete,
        region=parent.region,
        currency=parent.currency,
        independent=parent.independent,
        follow=parent.follow if parent.follow.recursive else None,
    )


def iter_pages(
    vendor: VendorSources, vendor_id: str, out_dir: Optional[Path] = None
) -> Iterator[SourcePage]:
    """All pages of a vendor, including the ones discovered by an earlier fetch.

    Child pages are visited breadth-first, in the same order as
    `fetch.fetch_vendor` fetches them, so that a page
    linked from multiple parents gets the same id in all steps.
    """
    discovered = {}
    if out_dir and discovered_path(out_dir, vendor_id).exists():
        discovered = json.loads(discovered_path(out_dir, vendor_id).read_text())
    queue = list(vendor.pages)
    seen = {page.url for page in queue}
    while queue:
        page = queue.pop(0)
        yield page
        if page.follow:
            for url in discovered.get(page.id, []):
                if url not in seen:
                    seen.add(url)
                    queue.append(child_page(page, url))


def selected_vendors(
    sources: Sources,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
) -> List[Tuple[str, VendorSources]]:
    selected = []
    for vendor_id, vendor in sources.vendors.items():
        if include and vendor_id not in include:
            continue
        if exclude and vendor_id in exclude:
            continue
        selected.append((vendor_id, vendor))
    return selected
