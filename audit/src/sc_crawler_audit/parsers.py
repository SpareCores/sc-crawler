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

from .schema import (
    ComponentRate,
    DbPrice,
    DbSpec,
    Extraction,
    ServerPrice,
    ServerSpec,
    SourcePage,
)


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


# OCPU price part of OCI Database with PostgreSQL, billed on top of the compute
# shape of the nodes in the cost estimator
OCI_POSTGRESQL_OCPU_PART = "B99060"
# public price list, documented at
# https://docs.oracle.com/en-us/iaas/Content/GSG/Tasks/signingup_topic-Estimating_Costs.htm
OCI_PRICE_LIST_URL = (
    "https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/?currencyCode=USD"
)


def _oci_vcpus_per_ocpu(shape_name: str) -> int:
    """An OCPU is 2 vCPUs, except for the Arm A1 and Grace (GB200/GB300) shapes."""
    return 1 if re.search(r"\.(A1|GB\d+)\.", shape_name) else 2


def _oci_local_disk_gb(text: Optional[str]) -> Optional[float]:
    """Parse e.g. '3.2 TB NVMe SSD and Block Storage' or '16x 3.84TB Aura 10 NVMe'."""
    match = re.match(r"(?:(\d+)\s*x\s*)?([\d.]+)\s*TB", text or "")
    if not match:
        return 0 if (text or "").lower().startswith("block storage only") else None
    return round(int(match.group(1) or 1) * float(match.group(2)) * 1000)


def _oci_usd_prices(products: dict) -> Dict[str, float]:
    """Pay as you go USD price by part number, without the free tier (if any)."""
    prices = {}
    for item in products["items"]:
        for localization in item.get("currencyCodeLocalizations") or []:
            if localization["currencyCode"] != "USD":
                continue
            tiers = [
                price
                for price in localization["prices"]
                if price["model"] == "PAY_AS_YOU_GO"
            ]
            if tiers:
                tiers.sort(key=lambda price: price.get("rangeMin") or 0)
                prices[item["partNumber"]] = float(tiers[-1]["value"])
    return prices


def oci_estimator_shapes(
    shapes: dict, prices: Dict[str, float], page: SourcePage, vendor: str
) -> Extraction:
    """Extract the shapes of the OCI cost estimator with the prices of their parts.

    - Fixed VM and bare metal shapes: specs and hourly price (the sum of the
      OCPU, memory and local NVMe parts, or the GPU part times the GPU count).
    - Flexible VM shapes: per-vCPU, per-GiB and local NVMe rates.
    - PostgreSQL shapes: specs and prices of the fixed sizes for one and two
      nodes, and component rates for all sizes, with the PostgreSQL OCPU fee
      added on top of the compute shape, as in the estimator.
    """
    servers, server_prices, rates, db_specs, db_prices = [], [], [], [], []
    for shape in shapes["items"]:
        # e.g. "BM.GPU.GB200.4 (NVL72)"
        name = shape["name"].split(" ")[0]
        kind = name.split(".")[0]
        if shape.get("status") != "ACTIVE" or kind not in ("VM", "BM", "PostgreSQL"):
            continue
        parts = {p["type"]["value"]: p for p in shape["products"]}
        if "ocpu" not in parts or any(
            p["partNumber"] not in prices for p in parts.values()
        ):
            continue
        quote = json.dumps(
            {
                "name": shape["name"],
                "products": [
                    {
                        "type": p["type"]["value"],
                        "partNumber": p["partNumber"],
                        "qty": p["qty"],
                        "price": prices[p["partNumber"]],
                    }
                    for p in shape["products"]
                ],
                "bundleMemoryQty": shape.get("bundleMemoryQty"),
                "gpuQty": shape.get("gpuQty"),
                "gpuMemoryQty": shape.get("gpuMemoryQty"),
                "localDisk": shape.get("localDisk"),
            },
            sort_keys=True,
        )
        vcpus_per_ocpu = _oci_vcpus_per_ocpu(name)
        ocpus = parts["ocpu"]["qty"]
        ocpu_price = prices[parts["ocpu"]["partNumber"]]
        memory_price = (
            prices[parts["memory"]["partNumber"]] if "memory" in parts else None
        )
        is_database = kind == "PostgreSQL"
        if is_database:
            ocpu_price += prices[OCI_POSTGRESQL_OCPU_PART]

        if not ocpus or parts["ocpu"].get("max"):
            # flexible shape: rates for any number of OCPUs and GB of memory
            if memory_price is None:
                continue
            common = dict(
                target="database" if is_database else "server",
                sku_prefix=f"{name}.",
                unit="hour",
                currency="USD",
                evidence_quote=quote,
            )
            rates.append(
                ComponentRate(
                    component="vcpu", price=ocpu_price / vcpus_per_ocpu, **common
                )
            )
            rates.append(
                ComponentRate(component="memory_gib", price=memory_price, **common)
            )
            if "disk" in parts:
                # priced per TB of local NVMe storage
                rates.append(
                    ComponentRate(
                        component="local_ssd_gib",
                        price=prices[parts["disk"]["partNumber"]] / 1000,
                        **common,
                    )
                )
            continue

        memory = shape.get("bundleMemoryQty")
        if is_database:
            node_price = ocpus * ocpu_price + parts["memory"]["qty"] * memory_price
            db_specs.append(
                DbSpec(
                    sku=name,
                    vcpus=int(ocpus * vcpus_per_ocpu),
                    memory_gib=memory,
                    evidence_quote=quote,
                )
            )
            for ha_level, ha_strategy, nodes in (
                (None, "none", 1),
                ("single_zone", "readable_cluster", 2),
                ("multi_zone", "readable_cluster", 2),
            ):
                db_prices.append(
                    DbPrice(
                        sku=name,
                        ha_level=ha_level,
                        ha_strategy=ha_strategy,
                        nodes=nodes,
                        deployment=f"{nodes} node(s) per cluster",
                        price=node_price * nodes,
                        unit="hour",
                        currency="USD",
                        evidence_quote=quote,
                    )
                )
            continue

        gpus = shape.get("gpuQty")
        disk_tb = parts["disk"]["qty"] if "disk" in parts else None
        # local disks without a separate part are included in the price
        storage_gb = (
            disk_tb * 1000 if disk_tb else _oci_local_disk_gb(shape.get("localDisk"))
        )
        servers.append(
            ServerSpec(
                sku=name,
                vcpus=int(ocpus * vcpus_per_ocpu),
                memory_gib=memory,
                gpu_count=gpus,
                gpu_memory_total_gib=shape.get("gpuMemoryQty"),
                storage_gb=storage_gb,
                storage_type="nvme ssd" if storage_gb else None,
                status="active",
                evidence_quote=quote,
            )
        )
        if gpus:
            # the part of the GPU shapes is priced per GPU, with all included
            price = gpus * ocpu_price
        else:
            price = ocpus * ocpu_price
            if memory_price is not None:
                price += parts["memory"]["qty"] * memory_price
            if disk_tb:
                price += disk_tb * prices[parts["disk"]["partNumber"]]
        server_prices.append(
            ServerPrice(
                sku=name,
                price=price,
                unit="hour",
                currency="USD",
                evidence_quote=quote,
            )
        )
    return _extraction(
        page,
        vendor,
        "oci_cost_estimator",
        servers=servers,
        server_prices=server_prices,
        component_rates=rates,
        db_specs=db_specs,
        db_prices=db_prices,
        notes=f"build {(shapes.get('buildId') or {}).get('buildNumber')}",
    )


def oci_cost_estimator(body: bytes, page: SourcePage, vendor: str) -> Extraction:
    """Shapes of the OCI cost estimator at oracle.com/cloud/costestimator.html.

    The estimator is rendered from JSON files: the shapes (with the part numbers
    billed for each) are in the fetched file, and the prices of the parts are
    downloaded from the public price list.
    """
    from .fetch import USER_AGENT

    response = requests.get(
        OCI_PRICE_LIST_URL, headers={"User-Agent": USER_AGENT}, timeout=60
    )
    response.raise_for_status()
    return oci_estimator_shapes(
        json.loads(body), _oci_usd_prices(response.json()), page, vendor
    )


_AZURE_SIZE_ROW_RE = re.compile(r"^\|\s*(Standard_[A-Za-z0-9_\-]+)[\s\d]*\|")
_AZURE_HEADING_RE = re.compile(r"^(#{1,4}) (.+)$")


def _azure_size_name(name: str) -> str:
    """Drop footnote markers glued to a size name (Standard_E2_v3<sup>1</sup>)."""
    name = re.sub(r"(_v\d)\d+$", r"\1", name)
    return re.sub(r"^(Standard_[A-Za-z]+\d+[a-z]+)\d$", r"\1", name)


def _azure_series_name(heading: str) -> str:
    """Series name from a page heading, e.g. 'Dldsv5 sizes series' -> 'Dldsv5'."""
    name = re.sub(r"\((Preview|NVMe|SCSI)\)", "", heading.replace("\\", ""))
    name = re.sub(r"(?i)^sizes in the\s+", "", name)
    name = re.sub(
        r"(?i)\s*(sizes? series|series sizes|series products|series)\s*$", "", name
    )
    return name.strip(" -")


def azure_size_series(markdown: str, page: SourcePage, vendor: str) -> Extraction:
    """Sizes and their series from an Azure per-series docs page.

    The first table with size names after a series heading (the "Basics" tab)
    lists every size of that series. Pages covering more series (e.g. Ev3 and
    Esv3) have one heading per series. Size names that appear only in later
    tables are typos in the docs (e.g. Standard_M48bds_v3 on the Mbdsv4 page),
    so they are only reported in the notes.
    """
    if not page.url.endswith("-series"):
        return _extraction(page, vendor, "azure_size_series")  # family overviews
    servers, stray, seen = [], [], set()
    series, tables, in_table = None, 0, False
    for line in markdown.splitlines():
        line = line.replace("\\_", "_")
        heading = _AZURE_HEADING_RE.match(line)
        if heading:
            level, text = len(heading.group(1)), heading.group(2).strip()
            if level == 1 or (
                re.search(r"(?i)series", text)
                and not re.search(r"(?i)sizes in series|definition", text)
            ):
                series, tables = _azure_series_name(text), 0
            elif level == 2 and re.search(r"(?i)size(?!.*definition)", text):
                # e.g. "General Purpose Sizes", then "Compute Optimized Sizes"
                tables = 0
            elif level == 2:
                tables = 2  # e.g. "Size table definitions": no sizes of the series
            continue
        row = _AZURE_SIZE_ROW_RE.match(line)
        if row and not in_table:
            tables += 1
        in_table = bool(row) or (in_table and line.startswith("|"))
        if not row or not series:
            continue
        sku = _azure_size_name(row.group(1))
        if tables == 1 and sku not in seen:
            seen.add(sku)
            servers.append(
                ServerSpec(sku=sku, series=series, evidence_quote=line.strip()[:300])
            )
        elif tables > 1 and sku not in seen:
            stray.append(sku)
    notes = None
    if stray:
        notes = "Only in later tables (docs typos?): " + ", ".join(sorted(set(stray)))
    return _extraction(page, vendor, "azure_size_series", servers=servers, notes=notes)


# parsers of the SKU and series listing of a page, taking its Markdown
LISTING_PARSERS: Dict[str, Callable[[str, SourcePage, str], Extraction]] = {
    "azure_size_series": azure_size_series,
}


PARSERS: Dict[str, Callable[[bytes, SourcePage, str], Extraction]] = {
    "aws_ec2_ondemand": aws_ec2_ondemand,
    "aws_ec2_spot": aws_ec2_spot,
    "aws_rds_postgresql": aws_rds_postgresql,
    "alicloud_instance_price": alicloud_instance_price,
    "oci_cost_estimator": oci_cost_estimator,
}

# parsers that need to resolve the URL to fetch at run time
URL_RESOLVERS: Dict[str, Callable[[], str]] = {
    "alicloud_instance_price": alicloud_latest_price_url,
}
