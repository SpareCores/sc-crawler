"""Collect vendor URLs already referenced in the repository as candidate sources."""

import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from .schema import Sources
from .sources import is_allowed

URL_PATTERN = re.compile(r"https://[^\s\"'<>`)\]]+")

# not first-party or not about specs, prices, regions or database features
SKIP_PATTERNS = [
    r"pulumi\.com",
    r"terraform\.io",
    r"wikipedia\.org",
    r"medium\.com",
    r"github\.(com|io)",
    r"web\.archive\.org",
    r"news\.|blogs?\.",
    r"/blog/",
    r"status\.|/status",
    r"/compliance|/trust-center|sustainability|umweltschutz|zertifizierung|/esg",
    r"console\.|portal\.azure|/apis/library",
    r"authentication|credentials|create-credentials|environmentcredential|sdkref",
    r"googleapis\.com/compute/v1/projects",
    r"sparecores\.com",
    r"/api/?$|/api/#|api-docs|/reference/rest/|developer-reference|APIReference",
]


def collect_urls(root: Path, sources: Sources) -> Dict[str, List[dict]]:
    """Find vendor URLs in code and docs, grouped by vendor.

    Each URL comes with the places referencing it and the referencing line,
    so it's clear why our ingest cites it.
    """
    root = Path(root)
    files = [
        *root.glob("src/**/*.py"),
        *root.glob("docs/**/*.md"),
        root / "README.md",
        root / "CHANGELOG.md",
    ]
    known = {
        page.url.rstrip("/")
        for vendor in sources.vendors.values()
        for page in vendor.pages
    }
    found = defaultdict(lambda: defaultdict(list))
    for path in files:
        if not path.exists() or "audit" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            for url in URL_PATTERN.findall(line):
                url = url.rstrip(".,;:")
                if any(re.search(p, url, re.IGNORECASE) for p in SKIP_PATTERNS):
                    continue
                for vendor_id, vendor in sources.vendors.items():
                    if is_allowed(url, vendor.allowed_domains):
                        found[vendor_id][url].append(
                            {
                                "ref": f"{path.relative_to(root)}:{lineno}",
                                "context": line.strip()[:200],
                            }
                        )
                        break
    return {
        vendor_id: [
            {
                "url": url,
                "in_sources": url.split("#")[0].rstrip("/") in known,
                "refs": refs,
            }
            for url, refs in sorted(urls.items())
        ]
        for vendor_id, urls in sorted(found.items())
    }
