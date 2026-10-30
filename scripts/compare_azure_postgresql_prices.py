"""Compare Azure PostgreSQL Flexible Server hourly compute prices in a SC Crawler
SQLite database against the official pricing page.

The pricing page (https://azure.microsoft.com/en-us/pricing/details/postgresql/flexible-server/)
renders its region dropdown from the calculator JSON fetched below, which
covers all regions in one response, independently of the Retail Prices API
used by the crawler.

Usage: python scripts/compare_azure_postgresql_prices.py path/to/sc-data-all.db
"""

import argparse
import json
import re
import sqlite3
import urllib.request
from collections import Counter

CALCULATOR_URL = (
    "https://azure.microsoft.com/api/v3/pricing/postgresql/calculator/?culture=en-us"
)
# DB prices are rounded to 4 decimals, the page shows up to 5
TOLERANCE = 0.0001


def official_prices() -> tuple[dict[tuple[str, str], float], dict[str, str]]:
    """Return {(region display name, database_id): hourly price} and slug -> display name."""
    request = urllib.request.Request(
        CALCULATOR_URL, headers={"User-Agent": "Mozilla/5.0"}
    )
    data = json.load(urllib.request.urlopen(request, timeout=60))
    regions = {region["slug"]: region["displayName"] for region in data["regions"]}
    prices = {}
    for key, offer in data["offers"].items():
        # e.g. flexible-server-generalpurpose-amd-compute-d8adsv5 -> Standard_D8ads_v5
        match = re.search(r"-compute-([a-z]+)(\d+)([a-z]*?)(?:v(\d+))?$", key)
        if not match:
            continue
        database_id = f"Standard_{match[1].upper()}{match[2]}{match[3]}"
        if match[4]:
            database_id += f"_v{match[4]}"
        for slug, price in offer["prices"].get("perhour", {}).items():
            prices[(regions.get(slug, slug), database_id)] = price["value"]
    return prices, regions


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("db", help="path to the SC Crawler SQLite database")
    parser.add_argument(
        "--details", action="store_true", help="list every mismatching row"
    )
    args = parser.parse_args()

    con = sqlite3.connect(args.db)
    region_ids = dict(
        con.execute("SELECT name, region_id FROM region WHERE vendor_id = 'azure'")
    )
    ours = {
        (region_id, database_id): price
        for region_id, database_id, price in con.execute(
            "SELECT region_id, database_id, price FROM database_price "
            "WHERE vendor_id = 'azure' AND ha = 'NONE' AND status = 'ACTIVE'"
        )
    }

    official, regions = official_prices()
    unknown_regions = sorted(
        {name for name in regions.values() if name not in region_ids}
    )
    stats = Counter()
    mismatches, missing = [], []
    for (region_name, database_id), price in sorted(official.items()):
        region_id = region_ids.get(region_name)
        if region_id is None:
            stats["region not in db"] += 1
            continue
        our_price = ours.get((region_id, database_id))
        if our_price is None:
            stats["missing from db"] += 1
            missing.append((region_id, database_id))
        elif abs(our_price - price) < 1e-9:
            stats["exact"] += 1
        elif abs(our_price - price) <= TOLERANCE:
            stats["within rounding"] += 1
        else:
            stats["mismatch"] += 1
            mismatches.append((region_id, database_id, our_price, price))
    compared = {(region_ids.get(r), d) for r, d in official}
    db_only = [key for key in ours if key not in compared]

    print(f"Official prices: {len(official)}, DB prices: {len(ours)}")
    for name, count in stats.most_common():
        print(f"  {name}: {count}")
    print(f"  in db but not on official page: {len(db_only)}")
    print(f"Official regions not in db: {unknown_regions}")
    print(
        "Missing from db by region:",
        Counter(region for region, _ in missing).most_common(),
    )
    print(
        "In db but not on official page by family:",
        Counter(
            re.sub(r"\d+", "#", database_id) for _, database_id in db_only
        ).most_common(15),
    )
    print(f"Mismatches (> {TOLERANCE}):")
    for region_id, database_id, our_price, price in (
        mismatches if args.details else mismatches[:20]
    ):
        print(
            f"  {region_id:20} {database_id:22} db={our_price:<10} "
            f"official={price:<10} ratio={our_price / price:.3f}"
        )


if __name__ == "__main__":
    main()
