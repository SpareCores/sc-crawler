"""Deterministic parsers for official machine-readable vendor sources.

Some vendor pricing pages are rendered from public JSON files hosted by the
vendor. These are parsed without an LLM. Each parser takes the raw response
body and the page definition, and returns an `schema.Extraction`.
"""

import json
import re
from datetime import UTC, datetime
from typing import Callable, Dict, Optional

import requests

from .schema import DbPrice, DbSpec, Extraction, ServerPrice, ServerSpec, SourcePage


def _number(text: Optional[str]) -> Optional[float]:
    match = re.search(r"[\d.]+", text or "")
    return float(match.group()) if match else None


def _aws_storage(text: str) -> tuple[Optional[float], Optional[str]]:
    """Parse e.g. '2 x 1900 NVMe SSD' or 'EBS only'."""
    if not text or text.lower().startswith("ebs"):
        return 0, None
    match = re.match(r"(?:(\d+)\s*x\s*)?([\d,.]+)\s*(?:GB)?\s*(.*)", text, re.I)
    if not match:
        return None, None
    count = int(match.group(1) or 1)
    size = float(match.group(2).replace(",", ""))
    kind = match.group(3).lower()
    storage_type = "nvme ssd" if "nvme" in kind else "ssd" if "ssd" in kind else None
    if "hdd" in kind:
        storage_type = "hdd"
    return count * size, storage_type


def _aws_network(text: str) -> Optional[float]:
    if not text:
        return None
    value = _number(text)
    if value is None:
        return None
    return value / 1000 if "megabit" in text.lower() else value


def _extraction(page: SourcePage, vendor: str, parser: str, **kwargs) -> Extraction:
    return Extraction(
        vendor=vendor,
        page_id=page.id,
        extracted_at=datetime.now(UTC),
        extracted_by=f"parser:{parser}",
        **kwargs,
    )


def aws_ec2_ondemand(body: bytes, page: SourcePage, vendor: str) -> Extraction:
    """EC2 on-demand Linux prices and specs behind aws.amazon.com/ec2/pricing/on-demand/."""
    data = json.loads(body)
    servers, prices = [], []
    for region, items in data["regions"].items():
        for item in items.values():
            sku = item["Instance Type"]
            quote = json.dumps(item, sort_keys=True)
            storage_gb, storage_type = _aws_storage(item.get("Storage", ""))
            servers.append(
                ServerSpec(
                    sku=sku,
                    vcpus=int(item["vCPU"]) if item.get("vCPU") else None,
                    memory_gib=_number(item.get("Memory")),
                    storage_gb=storage_gb,
                    storage_type=storage_type,
                    network_gbps=_aws_network(item.get("Network Performance")),
                    evidence_quote=quote,
                )
            )
            prices.append(
                ServerPrice(
                    sku=sku,
                    region=region,
                    price=float(item["price"]),
                    unit="hour",
                    currency="USD",
                    evidence_quote=quote,
                )
            )
    return _extraction(
        page, vendor, "aws_ec2_ondemand", servers=servers, server_prices=prices
    )


def aws_ec2_spot(body: bytes, page: SourcePage, vendor: str) -> Extraction:
    """EC2 spot Linux prices behind aws.amazon.com/ec2/spot/pricing/."""
    data = json.loads(body)
    prices = []
    for region in data["config"]["regions"]:
        if page.region and region["region"] != page.region:
            continue
        for group in region["instanceTypes"]:
            for size in group["sizes"]:
                for column in size["valueColumns"]:
                    price = column["prices"].get("USD")
                    if column["name"] != "linux" or not _number(price):
                        continue
                    prices.append(
                        ServerPrice(
                            sku=size["size"],
                            region=region["region"],
                            allocation="spot",
                            price=float(price),
                            unit="hour",
                            currency="USD",
                            evidence_quote=json.dumps(
                                {"region": region["region"], **size}, sort_keys=True
                            ),
                        )
                    )
    return _extraction(page, vendor, "aws_ec2_spot", server_prices=prices)


def aws_rds_postgresql(body: bytes, page: SourcePage, vendor: str) -> Extraction:
    """RDS for PostgreSQL on-demand prices behind aws.amazon.com/rds/postgresql/pricing/."""
    data = json.loads(body)
    deployment_of = {}
    for set_name, keys in data["sets"].items():
        for key in keys:
            deployment_of.setdefault(key, set_name)
    specs, prices, seen = [], [], set()
    for region, items in data["regions"].items():
        if page.region and region != page.region:
            continue
        for key, item in items.items():
            sku = item.get("Instance Type")
            if not sku:
                continue
            deployment = deployment_of.get(key, "")
            quote = json.dumps({"set": deployment, **item}, sort_keys=True)
            if "readable standbys" in deployment:
                ha_level, ha_strategy = "multi_zone", "readable_cluster"
            elif "Multi-AZ" in deployment:
                ha_level, ha_strategy = "multi_zone", "passive_standby"
            elif "Single-AZ" in deployment:
                ha_level, ha_strategy = None, "none"
            else:
                ha_level, ha_strategy = None, None
            prices.append(
                DbPrice(
                    sku=sku,
                    region=region,
                    ha_level=ha_level,
                    ha_strategy=ha_strategy,
                    deployment=deployment,
                    price=float(item["price"]),
                    unit="hour",
                    currency="USD",
                    evidence_quote=quote,
                )
            )
            if item.get("vCPU") and sku not in seen:
                seen.add(sku)
                specs.append(
                    DbSpec(
                        sku=sku,
                        vcpus=int(item["vCPU"]),
                        memory_gib=_number(item.get("Memory")),
                        evidence_quote=quote,
                    )
                )
    return _extraction(
        page, vendor, "aws_rds_postgresql", db_specs=specs, db_prices=prices
    )


ALICLOUD_PRICE_URL = (
    "https://g.alicdn.com/aliyun/ecs-price-info-intl/{version}/price/download/"
    "instancePrice.json"
)


def alicloud_latest_price_url(start: str = "2.0.400", max_steps: int = 2000) -> str:
    """Find the most recent published version of the ECS price list.

    The file is republished about weekly under an increasing patch version,
    but the latest version is not linked statically, so probe upwards with
    exponential then binary search.
    """
    major, minor, patch = (int(x) for x in start.split("."))

    def exists(p: int) -> bool:
        url = ALICLOUD_PRICE_URL.format(version=f"{major}.{minor}.{p}")
        return requests.head(url, timeout=30).status_code == 200

    if not exists(patch):
        raise ValueError(f"Alibaba price list version {start} not found")
    low, step = patch, 1
    while step < max_steps and exists(low + step):
        low, step = low + step, step * 2
    high = low + step
    while high - low > 1:
        mid = (low + high) // 2
        low, high = (mid, high) if exists(mid) else (low, mid)
    return ALICLOUD_PRICE_URL.format(version=f"{major}.{minor}.{low}")


def alicloud_instance_price(body: bytes, page: SourcePage, vendor: str) -> Extraction:
    """ECS pay-as-you-go Linux prices behind alibabacloud.com/product/ecs-pricing-list."""
    data = json.loads(body)
    prices = []
    for key, value in data["pricingInfo"].items():
        region, sku, network, os, io = key.split("::")
        if os != "linux" or network != "vpc" or (page.region and region != page.region):
            continue
        hours = [h for h in value.get("hours", []) if h.get("period") == "1"]
        if not hours:
            continue
        # `price` may include a temporary promotion, `originalPrice` is the list price
        prices.append(
            ServerPrice(
                sku=sku,
                region=region,
                price=float(hours[0].get("originalPrice") or hours[0]["price"]),
                unit="hour",
                currency=data.get("currency", "USD"),
                evidence_quote=f"{key}: {json.dumps(hours[0], sort_keys=True)}",
            )
        )
    return _extraction(
        page,
        vendor,
        "alicloud_instance_price",
        server_prices=prices,
        notes=f"version {data.get('version')}, published {data.get('publicationDate')}",
    )


PARSERS: Dict[str, Callable[[bytes, SourcePage, str], Extraction]] = {
    "aws_ec2_ondemand": aws_ec2_ondemand,
    "aws_ec2_spot": aws_ec2_spot,
    "aws_rds_postgresql": aws_rds_postgresql,
    "alicloud_instance_price": alicloud_instance_price,
}

# parsers that need to resolve the URL to fetch at run time
URL_RESOLVERS: Dict[str, Callable[[], str]] = {
    "alicloud_instance_price": alicloud_latest_price_url,
}
