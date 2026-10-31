"""Download official vendor pages and convert them to Markdown for extraction.

Pages are stored as-is next to a Markdown rendering and a metadata file
(final URL, HTTP status, hash, timestamp), so every audit finding can be
traced back to the exact content it was based on.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import List, Optional
from urllib.parse import urldefrag, urljoin

import requests

from . import __version__
from .parsers import URL_RESOLVERS
from .schema import PageKind, SourcePage, VendorSources
from .sources import (
    child_page,
    discovered_path,
    is_allowed,
    page_slug,
    pages_dir,
)

USER_AGENT = f"sc-crawler-audit/{__version__} (+https://sparecores.com)"

# page kinds expected to contain tabular data
TABULAR_KINDS = {
    PageKind.SERVER_SPECS,
    PageKind.SERVER_PRICES,
    PageKind.COMPONENT_RATES,
    PageKind.GPU,
    PageKind.DB_SPECS,
    PageKind.DB_PRICES,
}


@dataclass
class FetchResult:
    vendor: str
    page_id: str
    url: str
    final_url: str
    status: int
    content_type: str
    sha256: str
    fetched_at: str
    raw_bytes: int
    markdown_chars: int
    table_rows: int
    js_suspect: bool
    no_tables: bool = False
    error: Optional[str] = None
    cached: bool = False


def html_to_markdown(html: str | bytes) -> str:
    """Strip page chrome and convert the remaining HTML to Markdown."""
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
        tag.decompose()
    for tag in soup.find_all(["nav", "footer", "header"]):
        tag.decompose()
    # some sites have multiple (e.g. an empty) main elements, so pick the largest
    candidates = soup.find_all(["main", "article"]) or [soup.body or soup]
    body = max(candidates, key=lambda tag: len(tag.get_text(strip=True)))
    markdown = markdownify(str(body), heading_style="ATX", strip=["img"])
    return re.sub(r"\n{3,}", "\n\n", markdown).strip() + "\n"


def extract_links(html: str, base_url: str) -> List[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        url = urldefrag(urljoin(base_url, a["href"]))[0]
        if url not in links:
            links.append(url)
    return links


def count_table_rows(markdown: str) -> int:
    return sum(1 for line in markdown.splitlines() if line.lstrip().startswith("|"))


def _is_fresh(meta_path: Path, ttl: timedelta) -> bool:
    if not meta_path.exists():
        return False
    meta = json.loads(meta_path.read_text())
    if meta.get("error") or meta.get("status") != 200:
        return False
    fetched_at = datetime.fromisoformat(meta["fetched_at"])
    return datetime.now(UTC) - fetched_at < ttl


def fetch_page(
    vendor_id: str,
    vendor: VendorSources,
    page: SourcePage,
    out_dir: Path,
    ttl: timedelta = timedelta(hours=24),
    dry_run: bool = False,
    session: Optional[requests.Session] = None,
) -> FetchResult:
    """Fetch a single page (or reuse a fresh cached copy) and store it."""
    target = pages_dir(out_dir, vendor_id)
    slug = page_slug(page.id)
    meta_path = target / f"{slug}.meta.json"
    if not dry_run and _is_fresh(meta_path, ttl):
        return FetchResult(**{**json.loads(meta_path.read_text()), "cached": True})

    now = datetime.now(UTC).isoformat()
    session = session or requests.Session()
    try:
        url = page.url
        if page.parser in URL_RESOLVERS:
            url = URL_RESOLVERS[page.parser]()
        headers = {"User-Agent": USER_AGENT}
        try:
            response = session.get(url, headers=headers, timeout=120)
        except requests.exceptions.ChunkedEncodingError:
            # some large pages break with compressed transfer
            headers["Accept-Encoding"] = "identity"
            response = session.get(url, headers=headers, timeout=300)
    except (requests.RequestException, ValueError) as e:
        return FetchResult(
            vendor_id, page.id, page.url, page.url, 0, "", "", now, 0, 0, 0, True,
            error=str(e),
        )  # fmt: skip

    error = None
    if not is_allowed(response.url, vendor.allowed_domains):
        error = f"Redirected outside allowed domains: {response.url}"
    elif response.status_code != 200:
        error = f"HTTP {response.status_code}"

    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    is_json = "json" in content_type or page.url.endswith(".json")
    if is_json:
        markdown = ""
    elif error is None:
        # pass bytes so that the page's own <meta charset> is used, as servers
        # often omit the charset in the header (e.g. AWS docs)
        markdown = html_to_markdown(response.content)
    else:
        markdown = ""
    table_rows = count_table_rows(markdown)
    js_suspect = not is_json and len(markdown) < 1500
    no_tables = not is_json and bool(set(page.kinds) & TABULAR_KINDS) and table_rows < 3

    result = FetchResult(
        vendor=vendor_id,
        page_id=page.id,
        url=page.url,
        final_url=response.url,
        status=response.status_code,
        content_type=content_type,
        sha256=hashlib.sha256(response.content).hexdigest(),
        fetched_at=now,
        raw_bytes=len(response.content),
        markdown_chars=len(markdown),
        table_rows=table_rows,
        js_suspect=js_suspect,
        no_tables=no_tables,
        error=error,
    )
    if dry_run:
        return result

    target.mkdir(parents=True, exist_ok=True)
    (target / f"{slug}.{'json' if is_json else 'html'}").write_bytes(response.content)
    if markdown:
        header = (
            f"<!-- source: {response.url} | fetched_at: {now} | "
            f"sha256: {result.sha256} -->\n\n"
        )
        (target / f"{slug}.md").write_text(header + markdown)
    meta_path.write_text(json.dumps(asdict(result), indent=2))

    if page.follow and error is None:
        pattern = re.compile(page.follow.pattern)
        if is_json:
            # e.g. a docs table of contents with (relative) "href" values
            links = [
                urldefrag(urljoin(response.url, href))[0]
                for href in re.findall(r'"href"\s*:\s*"([^"]+)"', response.text)
            ]
        else:
            links = extract_links(response.text, response.url)
        children = list(
            dict.fromkeys(
                url
                for url in links
                if pattern.search(url) and is_allowed(url, vendor.allowed_domains)
            )
        )[: page.follow.max_pages]
        path = discovered_path(out_dir, vendor_id)
        discovered = json.loads(path.read_text()) if path.exists() else {}
        discovered[page.id] = children
        path.write_text(json.dumps(discovered, indent=2))
    return result


def fetch_vendor(
    vendor_id: str,
    vendor: VendorSources,
    out_dir: Path,
    ttl: timedelta = timedelta(hours=24),
    dry_run: bool = False,
    page_filter: Optional[str] = None,
    progress=None,
) -> List[FetchResult]:
    """Fetch all pages of a vendor, including child pages linked from `follow` pages."""
    session = requests.Session()
    results = []
    queue = [
        page
        for page in vendor.pages
        if not page_filter or re.search(page_filter, page.id)
    ]
    seen = {page.url for page in queue}
    while queue:
        page = queue.pop(0)
        result = fetch_page(vendor_id, vendor, page, out_dir, ttl, dry_run, session)
        results.append(result)
        if progress:
            progress(result)
        path = discovered_path(out_dir, vendor_id)
        if page.follow and not dry_run and not result.error and path.exists():
            for url in json.loads(path.read_text()).get(page.id, []):
                if url not in seen:
                    seen.add(url)
                    queue.append(child_page(page, url))
    return results
