"""Compare extracted vendor data with our records and produce findings.

Everything here is deterministic: the LLM only extracts rows from vendor
pages, and all unit conversions, matching and tolerances are applied here.
"""

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .export import Ours, norm
from .schema import Extraction, PageKind, SourcePage, VendorSources
from .sources import extracted_dir, iter_pages, page_slug

MIB_PER_GIB = 1024

# where to look first in our ingest code for each finding type
CODE_HINTS = {
    "server": "inventory_servers",
    "server_price": "inventory_server_prices",
    "server_price_spot": "inventory_server_prices_spot",
    "database": "inventory_databases",
    "database_price": "inventory_database_prices",
    "region": "inventory_regions",
}


@dataclass
class Finding:
    vendor: str
    type: str
    severity: str
    page_id: str
    url: str
    independent: bool
    feed: bool = False
    spec_authority: bool = True
    sku: Optional[str] = None
    our_id: Optional[str] = None
    region: Optional[str] = None
    field: Optional[str] = None
    ours: object = None
    theirs: object = None
    diff_pct: Optional[float] = None
    quote: Optional[str] = None
    code_hint: Optional[str] = None
    matched_by: Optional[str] = None
    note: Optional[str] = None
    also_on_pages: List[str] = dc_field(default_factory=list)
    # set from triage.yaml, see triage.py
    verdict: Optional[str] = None
    triage_note: Optional[str] = None
    triage_issue: Optional[str] = None

    def key(self) -> tuple:
        return (
            self.type,
            self.sku and norm(self.sku),
            self.our_id,
            self.region,
            self.field,
            str(self.ours),
            str(self.theirs),
        )

    def to_dict(self) -> dict:
        return asdict(self)


def rel_diff(ours: float, theirs: float) -> float:
    if theirs == 0:
        return 0.0 if ours == 0 else float("inf")
    return (ours - theirs) / theirs


def major_version(version) -> str:
    """PostgreSQL major version: '16.4' -> '16', but '9.6.24' -> '9.6'."""
    parts = str(version).split(".")
    if parts[0].isdigit() and int(parts[0]) < 10 and len(parts) > 1:
        return ".".join(parts[:2])
    return parts[0]


def monthly_cap_hours(price_tiered) -> Optional[float]:
    """Hours after which a tiered hourly price becomes free (i.e. the monthly cap)."""
    tiers = price_tiered if isinstance(price_tiered, list) else []
    for previous, tier in zip(tiers, tiers[1:]):
        if previous.get("price") and tier.get("price") == 0:
            return float(tier["lower"])
    return None


def contains_either(ours: Optional[str], theirs: Optional[str]) -> bool:
    """Names match if one contains the other, or all words of one are in the other."""
    a, b = norm(ours), norm(theirs)
    if not (a and b):
        return False
    if a in b or b in a:
        return True
    words_a = set(re.findall(r"[a-z0-9]+", str(ours).lower()))
    words_b = set(re.findall(r"[a-z0-9]+", str(theirs).lower()))
    return words_a <= words_b or words_b <= words_a


class Comparer:
    def __init__(
        self,
        vendor_id: str,
        vendor: VendorSources,
        ours: Ours,
        price_tolerance: float = 0.01,
    ):
        self.vendor_id = vendor_id
        self.vendor = vendor
        self.ours = ours
        self.price_tolerance = price_tolerance
        self.findings: List[Finding] = []
        self.stats: Counter = Counter()
        # vendor SKU labels resolved by matching specs, reused for prices
        self.spec_matches: Dict[str, dict] = {}
        # (our server id) seen on any spec page / (server, region) on price pages
        self.seen_servers: set = set()
        self.seen_prices: set = set()
        self.seen_databases: set = set()
        self.seen_regions: set = set()
        # pages agreeing with our value per (our id, field), to spot source conflicts
        self.agreements: Dict[tuple, set] = defaultdict(set)
        # (our id, field) pairs checked by at least one authoritative page
        self.checked_by_authority: set = set()
        self.authoritative_pages: set = set()
        self.active_regions = {
            r["region_id"] for r in ours.regions if r["status"] == "ACTIVE"
        }

    # ##########################################################################
    # helpers

    def add(self, page: SourcePage, type_: str, severity: str, hint: str, **kwargs):
        if type_ in ("STATUS_MISMATCH", "PRICE_MISSING_IN_DB", "NOT_AT_VENDOR"):
            # our status is aggregated over all regions, while the vendor page may
            # only cover some: show where we have prices to help the triage
            regions = sorted(self.ours.price_regions.get(kwargs.get("our_id"), []))
            if kwargs.get("our_id") and hint.startswith("server"):
                where = ", ".join(regions[:15]) + (" ..." if len(regions) > 15 else "")
                context = f"Our active prices: {where or 'none'}."
                kwargs["note"] = " ".join(filter(None, [kwargs.get("note"), context]))
        self.findings.append(
            Finding(
                vendor=self.vendor_id,
                type=type_,
                severity=severity,
                page_id=page.id,
                url=page.url,
                independent=page.independent,
                feed=bool(page.parser),
                spec_authority=page.spec_authority,
                code_hint=f"vendors/_{self.vendor_id}.py:{CODE_HINTS[hint]}",
                **kwargs,
            )
        )

    def ipv4_monthly(self, region_id: str) -> float:
        """Our monthly price of a public IPv4 address in a region."""
        row = self.ours.ipv4_prices.get(region_id)
        if not row:
            return 0.0
        if row["unit"] == "HOUR":
            return row["price"] * self.vendor.hours_per_month
        return row["price"]

    def to_hourly(self, price: float, unit: str) -> float:
        return price / self.vendor.hours_per_month if unit == "month" else price

    def region_of(self, region: Optional[str], page: SourcePage) -> Optional[str]:
        """Our active region id for a region named on a vendor page."""
        region_id = self.ours.find_region(region or page.region)
        if region_id and region_id not in self.active_regions:
            self.stats["skipped_inactive_region"] += 1
            return None
        return region_id

    def covered(self, pattern: Optional[str], *names: Optional[str]) -> bool:
        if not pattern:
            return True
        return any(re.search(pattern, n or "", re.IGNORECASE) for n in names)

    def resolve_server(
        self, sku: str, spec=None, page=None
    ) -> Tuple[Optional[dict], str]:
        servers = self.ours.find_servers(sku)
        if servers:
            return servers[0], "name"
        if norm(sku) in self.spec_matches:
            return self.spec_matches[norm(sku)], "specs"
        if spec is None or spec.vcpus is None or spec.memory_gib is None:
            return None, ""
        candidates = [
            s
            for s in self.ours.servers
            if s["status"] == "ACTIVE"
            and s["vcpus"] == spec.vcpus
            and abs(rel_diff(s["memory_amount"] / MIB_PER_GIB, spec.memory_gib)) < 0.01
            and (
                not spec.storage_gb
                or abs(rel_diff(s["storage_size"] or 0, spec.storage_gb)) < 0.01
            )
            and (
                spec.gpu_count is None
                or (s["accelerator_count"] or 0) == spec.gpu_count
            )
            and (page is None or self.covered(page.covers, s["server_id"], s["name"]))
        ]
        if len(candidates) == 1:
            self.spec_matches[norm(sku)] = candidates[0]
            return candidates[0], "specs"
        if len(candidates) > 1:
            return None, f"ambiguous:{len(candidates)}"
        return None, ""

    # ##########################################################################
    # servers

    def compare_server_spec(self, page: SourcePage, spec):
        self.stats["server_specs"] += 1
        server, matched_by = self.resolve_server(spec.sku, spec, page)
        if server is None:
            if matched_by.startswith("ambiguous"):
                self.stats["server_specs_ambiguous"] += 1
                return
            if spec.status in ("retired", "retiring"):
                # whole series retired: check our servers of that family
                series = norm(re.sub(r"[- ]?series$", "", spec.sku, flags=re.I))
                for s in self.ours.servers:
                    if (
                        s["status"] == "ACTIVE"
                        and series
                        and norm(s["family"]) == series
                    ):
                        self.add(
                            page, "STATUS_MISMATCH", "medium", "server",
                            sku=spec.sku, our_id=s["server_id"], field="status",
                            ours=s["status"], theirs=spec.status,
                            quote=spec.evidence_quote, matched_by="family",
                        )  # fmt: skip
                return
            if spec.status == "unavailable":
                self.add(
                    page, "MISSING_IN_DB", "low", "server", sku=spec.sku,
                    quote=spec.evidence_quote,
                    note="Listed by the vendor as not orderable (e.g. end of sale).",
                )  # fmt: skip
                return
            if set(page.kinds) == {PageKind.LIFECYCLE} or re.search(
                r"[- ]series$", spec.sku, re.IGNORECASE
            ):
                # rows naming whole series instead of sizes (e.g. overview pages)
                self.stats["series_rows_unmatched"] += 1
                return
            self.add(
                page, "MISSING_IN_DB", "medium", "server", sku=spec.sku,
                theirs={k: v for k, v in spec.model_dump().items()
                        if v is not None and k != "evidence_quote"},
                quote=spec.evidence_quote,
                note="SKU listed by the vendor but not found among our servers.",
            )  # fmt: skip
            return
        self.seen_servers.add(server["server_id"])
        common = dict(
            sku=spec.sku,
            our_id=server["server_id"],
            quote=spec.evidence_quote,
            matched_by=matched_by,
        )

        if server["status"] != "ACTIVE" and spec.status in (None, "active"):
            # docs pages often stay up for a while after retirement
            retiring = server["status"] in ("RETIRED", "PLANNED_FOR_RETIREMENT")
            self.add(
                page, "STATUS_MISMATCH", "low" if retiring else "medium", "server",
                field="status", ours=server["status"],
                theirs=spec.status or "listed", **common,
            )  # fmt: skip
        if server["status"] == "ACTIVE" and spec.status == "unavailable":
            self.add(
                page, "STATUS_MISMATCH", "low", "server", field="status",
                ours=server["status"], theirs=spec.status,
                note="Listed as currently not orderable by the vendor.", **common,
            )  # fmt: skip
        expected_status = {
            "retired": {"RETIRED"},
            # retiring SKUs may be still orderable for a while
            "retiring": {"PLANNED_FOR_RETIREMENT", "RETIRED"},
        }.get(spec.status)
        if expected_status and server["status"] not in expected_status:
            self.add(
                page, "STATUS_MISMATCH",
                "medium" if server["status"] == "ACTIVE" else "low", "server",
                field="status", ours=server["status"], theirs=spec.status,
                note=f"Expected {' or '.join(sorted(expected_status))}.", **common,
            )  # fmt: skip
        if PageKind.LIFECYCLE in page.kinds and set(page.kinds) == {PageKind.LIFECYCLE}:
            return

        def check(field_, ours, theirs, severity, tolerance=0.0, absolute=False):
            if theirs is None:
                return
            if ours is None:
                self.add(
                    page, "VALUE_MISSING_IN_DB", "info", "server", field=field_,
                    theirs=theirs, **common,
                )  # fmt: skip
                return
            if absolute:
                ok = ours == theirs
                diff = None
            else:
                diff = rel_diff(float(ours), float(theirs))
                ok = abs(diff) <= tolerance
            if page.spec_authority:
                self.checked_by_authority.add((server["server_id"], field_))
            if ok:
                self.agreements[(server["server_id"], field_)].add(page.id)
            else:
                self.add(
                    page, "SPEC_MISMATCH", severity, "server", field=field_,
                    ours=ours, theirs=theirs,
                    diff_pct=None if diff is None else round(diff * 100, 2),
                    **common,
                )  # fmt: skip

        check("vcpus", server["vcpus"], spec.vcpus, "high", absolute=True)
        check(
            "memory_gib",
            server["memory_amount"] / MIB_PER_GIB if server["memory_amount"] else None,
            spec.memory_gib,
            "high",
            tolerance=0.01,
        )
        check(
            "gpu_count",
            server["accelerator_count"] or 0,
            spec.gpu_count,
            "high",
            tolerance=0.01,  # fractional GPUs, e.g. 1/6 vs 0.1667
        )
        if spec.gpu_model and (spec.gpu_count or 0) > 0:
            if not contains_either(server["accelerator_model"], spec.gpu_model):
                self.add(
                    page, "SPEC_MISMATCH", "high", "server", field="gpu_model",
                    ours=server["accelerator_model"], theirs=spec.gpu_model, **common,
                )  # fmt: skip
        check(
            "gpu_memory_total_gib",
            (server["accelerator_memory_total"] or 0) / MIB_PER_GIB
            if server["accelerator_count"]
            else None,
            spec.gpu_memory_total_gib if (spec.gpu_count or 0) > 0 else None,
            "medium",
            tolerance=0.05,
        )
        check("storage_gb", server["storage_size"], spec.storage_gb, "medium",
              tolerance=0.01)  # fmt: skip
        if spec.storage_type and spec.storage_gb:
            ours_type = (server["storage_type"] or "").lower().replace("_", " ")
            if page.spec_authority:
                self.checked_by_authority.add((server["server_id"], "storage_type"))
            if ours_type == spec.storage_type:
                self.agreements[(server["server_id"], "storage_type")].add(page.id)
            else:
                self.add(
                    page, "SPEC_MISMATCH", "low", "server", field="storage_type",
                    ours=server["storage_type"], theirs=spec.storage_type, **common,
                )  # fmt: skip
        if spec.network_gbps is not None:
            ours_net = server["network_speed_max"] or server["network_speed_baseline"]
            check("network_gbps", ours_net, spec.network_gbps, "low", tolerance=0.01)
        if spec.cpu_model and server["cpu_model"]:
            # vendors often name the CPU generation or brand (e.g. "Ice Lake",
            # "Graviton4") instead of the model, so only compare model numbers
            ours_numbers = set(re.findall(r"\d{4,}", norm(server["cpu_model"])))
            their_numbers = set(re.findall(r"\d{4,}", norm(spec.cpu_model)))
            if ours_numbers and their_numbers and not ours_numbers & their_numbers:
                self.add(
                    page, "SPEC_MISMATCH", "low", "server", field="cpu_model",
                    ours=server["cpu_model"], theirs=spec.cpu_model,
                    note="Our CPU fields may come from benchmark hardware inspection.",
                    **common,
                )  # fmt: skip
        if spec.cpu_manufacturer and server["cpu_manufacturer"]:
            if not contains_either(server["cpu_manufacturer"], spec.cpu_manufacturer):
                self.add(
                    page, "SPEC_MISMATCH", "low", "server", field="cpu_manufacturer",
                    ours=server["cpu_manufacturer"], theirs=spec.cpu_manufacturer,
                    **common,
                )  # fmt: skip

    def compare_server_price(self, page: SourcePage, price):
        self.stats["server_prices"] += 1
        if price.operating_system != "linux":
            return
        region_id = self.region_of(price.region, page)
        if region_id is None:
            self.stats["server_prices_unknown_region"] += 1
            return
        server, matched_by = self.resolve_server(price.sku)
        hint = "server_price_spot" if price.allocation == "spot" else "server_price"
        if server is None:
            self.stats["server_prices_unmatched_sku"] += 1
            return
        theirs = self.to_hourly(price.price, price.unit)
        candidates = [
            p
            for p in self.ours.prices_by_server_region.get(
                (server["server_id"], region_id), []
            )
            if p["allocation"] == price.allocation.upper()
            and p["operating_system"].lower() == "linux"
        ]
        self.seen_prices.add((server["server_id"], region_id, price.allocation))
        common = dict(
            sku=price.sku,
            our_id=server["server_id"],
            region=region_id,
            quote=price.evidence_quote,
            matched_by=matched_by,
        )
        if not candidates:
            severity = "low" if price.allocation == "spot" else "medium"
            if server["status"] != "ACTIVE":
                severity = "low"
            if not page.implies_availability:
                severity = "info"
            self.add(
                page, "PRICE_MISSING_IN_DB", severity, hint,
                field=f"{price.allocation} price", theirs=f"{theirs:.6f} {price.currency}",
                note=f"Our server status: {server['status']}.", **common,
            )  # fmt: skip
            return
        same_currency = [p for p in candidates if p["currency"] == price.currency]
        if not same_currency:
            self.stats["server_prices_other_currency"] += 1
            return
        ipv4 = self.ipv4_monthly(region_id) if page.prices_include_ipv4 else 0.0

        def comparable(p: dict) -> float:
            """Our price in the unit of the vendor's price, incl. what the vendor includes."""
            cap_hours = monthly_cap_hours(p.get("price_tiered"))
            hours = self.vendor.hours_per_month
            if price.unit == "month":
                if self.vendor.monthly_price_is_cap and cap_hours:
                    hours = cap_hours
                return p["price"] * hours + ipv4
            return p["price"] + ipv4 / (cap_hours or hours)

        best = min(same_currency, key=lambda p: abs(comparable(p) - price.price))
        ours_value = comparable(best)
        diff = rel_diff(ours_value, price.price)
        tolerance = self.price_tolerance
        if price.allocation == "spot":
            # spot prices move constantly, flag only large differences
            tolerance = max(tolerance, 0.25)
        min_abs = 0.005 if price.unit == "month" else 0.00005
        if abs(diff) > tolerance and abs(ours_value - price.price) > min_abs:
            severity = (
                "low"
                if price.allocation == "spot"
                else "high"
                if abs(diff) > 0.05
                else "medium"
            )
            adjustments = []
            if ipv4:
                adjustments.append("incl. IPv4")
            if price.unit == "month":
                adjustments.append(
                    "monthly cap"
                    if self.vendor.monthly_price_is_cap
                    else "hourly x hours/month"
                )
            self.add(
                page, "PRICE_MISMATCH", severity, hint,
                field=f"{price.allocation} {price.unit}ly price",
                ours=f"{ours_value:.6f} {best['currency']}"
                + (f" ({', '.join(adjustments)}; hourly {best['price']})" if adjustments else ""),
                theirs=f"{price.price:.6f} {price.currency}",
                diff_pct=round(diff * 100, 2), **common,
            )  # fmt: skip

    def compare_component_rates(self, page: SourcePage, rates):
        groups = defaultdict(dict)
        for rate in rates:
            key = (
                rate.target,
                rate.sku_prefix.lower(),
                self.region_of(rate.region, page),
                rate.allocation,
                rate.ha_level,
                rate.currency,
            )
            groups[key][rate.component] = rate
        for (
            target,
            prefix,
            region_id,
            allocation,
            ha_level,
            currency,
        ), parts in groups.items():
            if region_id is None or "vcpu" not in parts or "memory_gib" not in parts:
                continue
            self.stats["component_rate_groups"] += 1
            quote = " | ".join(r.evidence_quote for r in parts.values())
            if target == "server":
                self._compare_server_components(
                    page, prefix, region_id, allocation, currency, parts, quote
                )
            else:
                self._compare_db_components(
                    page, prefix, region_id, ha_level, currency, parts, quote
                )

    def _compare_server_components(
        self, page, prefix, region_id, allocation, currency, parts, quote
    ):
        for server in self.ours.servers:
            if server["status"] != "ACTIVE" or not server[
                "server_id"
            ].lower().startswith(prefix):
                continue
            gpus = server["accelerator_count"] or 0
            if gpus and "gpu" not in parts:
                continue
            expected = (
                self.to_hourly(parts["vcpu"].price, parts["vcpu"].unit)
                * server["vcpus"]
                + self.to_hourly(parts["memory_gib"].price, parts["memory_gib"].unit)
                * server["memory_amount"]
                / MIB_PER_GIB
            )
            if gpus:
                expected += self.to_hourly(parts["gpu"].price, parts["gpu"].unit) * gpus
            if server["storage_size"] and "local_ssd_gib" in parts:
                ssd = parts["local_ssd_gib"]
                expected += self.to_hourly(ssd.price, ssd.unit) * server["storage_size"]
            ours = [
                p
                for p in self.ours.prices_by_server_region.get(
                    (server["server_id"], region_id), []
                )
                if p["allocation"] == allocation.upper() and p["currency"] == currency
            ]
            if not ours:
                continue
            best = min(ours, key=lambda p: abs(p["price"] - expected))
            diff = rel_diff(best["price"], expected)
            if abs(diff) > max(self.price_tolerance, 0.01):
                self.add(
                    page, "COMPONENT_PRICE_MISMATCH",
                    "high" if abs(diff) > 0.05 else "medium",
                    "server_price_spot" if allocation == "spot" else "server_price",
                    sku=server["server_id"], our_id=server["server_id"],
                    region=region_id, field=f"{allocation} hourly price",
                    ours=f"{best['price']:.6f} {currency}",
                    theirs=f"{expected:.6f} {currency} (from {prefix}* rates)",
                    diff_pct=round(diff * 100, 2), quote=quote,
                    note="Vendor rates x our vCPUs/memory/GPUs/local SSD.",
                )  # fmt: skip

    def _compare_db_components(
        self, page, prefix, region_id, ha_level, currency, parts, quote
    ):
        for db in self.ours.databases:
            if db["status"] != "ACTIVE" or not db["database_id"].lower().startswith(
                prefix
            ):
                continue
            if not db["vcpus"] or not db["memory_amount"]:
                continue
            expected = (
                self.to_hourly(parts["vcpu"].price, parts["vcpu"].unit) * db["vcpus"]
                + self.to_hourly(parts["memory_gib"].price, parts["memory_gib"].unit)
                * db["memory_amount"]
                / MIB_PER_GIB
            )
            ours = [
                p
                for p in self.ours.db_prices_by_db_region.get(
                    (db["database_id"], region_id), []
                )
                if p["currency"] == currency
                and (p["ha"] or "NONE") == (ha_level or "none").upper()
            ]
            if not ours:
                continue
            best = min(ours, key=lambda p: abs(p["price"] - expected))
            diff = rel_diff(best["price"], expected)
            if abs(diff) > max(self.price_tolerance, 0.01):
                self.add(
                    page, "COMPONENT_PRICE_MISMATCH",
                    "high" if abs(diff) > 0.05 else "medium", "database_price",
                    sku=db["database_id"], our_id=db["database_id"], region=region_id,
                    field=f"hourly price (ha={best['ha']})",
                    ours=f"{best['price']:.6f} {currency}",
                    theirs=f"{expected:.6f} {currency} (from {prefix}* rates)",
                    diff_pct=round(diff * 100, 2), quote=quote,
                    note="Vendor per-vCPU and per-GiB rates x our vCPUs/memory.",
                )  # fmt: skip

    # ##########################################################################
    # databases

    def mark_database_seen(self, page: SourcePage, *database_ids: str):
        self.seen_databases.update(database_ids)

    def check_db_status(self, page: SourcePage, db: dict, **common):
        """A database SKU listed on a complete page should be active in our data.

        Unlike VM size pages, which often stay up after retirement, the database
        size lists of the vendors only show what can be created.
        """
        if page.complete and db["status"] != "ACTIVE":
            self.add(
                page, "STATUS_MISMATCH", "medium", "database", field="status",
                ours=db["status"], theirs="listed", **common,
            )  # fmt: skip

    def compare_db_spec(self, page: SourcePage, spec):
        self.stats["db_specs"] += 1
        dbs = self.ours.find_databases(spec.sku)
        if not dbs:
            # a whole series (e.g. Azure "Dcadsv5" with a vCore range) covers
            # all our sizes of that family, without comparing specs
            family = [
                db for db in self.ours.databases if norm(db["family"]) == norm(spec.sku)
            ]
            if family:
                self.mark_database_seen(page, *(db["database_id"] for db in family))
                for db in family:
                    self.check_db_status(
                        page, db, sku=spec.sku, our_id=db["database_id"],
                        quote=spec.evidence_quote,
                    )  # fmt: skip
                self.stats["db_series_rows"] += 1
                return
            self.add(
                page, "MISSING_IN_DB", "medium", "database", sku=spec.sku,
                theirs={k: v for k, v in spec.model_dump().items()
                        if v is not None and k != "evidence_quote"},
                quote=spec.evidence_quote,
                note="Database SKU listed by the vendor but not found among ours.",
            )  # fmt: skip
            return
        db = dbs[0]
        self.mark_database_seen(page, db["database_id"])
        common = dict(sku=spec.sku, our_id=db["database_id"], quote=spec.evidence_quote)
        self.check_db_status(page, db, **common)
        pairs = [
            ("vcpus", db["vcpus"], spec.vcpus, "high", 0.0),
            (
                "memory_gib",
                db["memory_amount"] / MIB_PER_GIB if db["memory_amount"] else None,
                spec.memory_gib,
                "high",
                0.01,
            ),
            ("storage_gb", db["storage_size"], spec.storage_gb, "medium", 0.01),
        ]
        for field_, ours, theirs, severity, tolerance in pairs:
            if theirs is None:
                continue
            if ours is None:
                self.add(page, "VALUE_MISSING_IN_DB", "info", "database",
                         field=field_, theirs=theirs, **common)  # fmt: skip
                continue
            diff = rel_diff(float(ours), float(theirs))
            if abs(diff) <= tolerance:
                self.agreements[(db["database_id"], field_)].add(page.id)
            else:
                self.add(
                    page, "SPEC_MISMATCH", severity, "database", field=field_,
                    ours=ours, theirs=theirs, diff_pct=round(diff * 100, 2), **common,
                )  # fmt: skip

    def compare_db_price(self, page: SourcePage, price):
        self.stats["db_prices"] += 1
        region_id = self.region_of(price.region, page)
        if region_id is None:
            self.stats["db_prices_unknown_region"] += 1
            return
        dbs = self.ours.find_databases(price.sku)
        if not dbs:
            self.stats["db_prices_unmatched_sku"] += 1
            return
        db = dbs[0]
        theirs = self.to_hourly(price.price, price.unit)
        candidates = [
            p
            for p in self.ours.db_prices_by_db_region.get(
                (db["database_id"], region_id), []
            )
            if p["currency"] == price.currency
            and (price.ha_level is None or p["ha"] == price.ha_level.upper())
            and (
                price.ha_strategy is None
                or p["ha_strategy"] == price.ha_strategy.upper()
            )
        ]
        common = dict(
            sku=price.sku, our_id=db["database_id"], region=region_id,
            quote=price.evidence_quote,
        )  # fmt: skip
        variant = (
            price.deployment or f"ha={price.ha_level}, strategy={price.ha_strategy}"
        )
        if not candidates:
            self.add(
                page, "PRICE_MISSING_IN_DB", "low", "database_price",
                field=f"price ({variant})", theirs=f"{theirs:.6f} {price.currency}",
                **common,
            )  # fmt: skip
            return
        best = min(candidates, key=lambda p: abs(p["price"] - theirs))
        diff = rel_diff(best["price"], theirs)
        tolerance = max(self.price_tolerance, 0.02 if price.unit == "month" else 0)
        if abs(diff) > tolerance and abs(best["price"] - theirs) > 0.00005:
            self.add(
                page, "PRICE_MISMATCH", "high" if abs(diff) > 0.05 else "medium",
                "database_price", field=f"hourly price ({variant})",
                ours=f"{best['price']:.6f} {best['currency']} "
                f"(ha={best['ha']}, strategy={best['ha_strategy']})",
                theirs=f"{theirs:.6f} {price.currency}", diff_pct=round(diff * 100, 2),
                **common,
            )  # fmt: skip

    FEATURE_COLUMNS = {
        "sla": "sla",
        "max_read_replicas": "max_read_replicas",
        "continuous_backups_days": "continuous_backups",
        "storage_extra_max_gb": "storage_extra_max",
        "engine_versions": "engine_versions",
    }

    def compare_db_feature(self, page: SourcePage, feature):
        self.stats["db_features"] += 1
        column = self.FEATURE_COLUMNS[feature.feature]
        dbs = [
            db
            for db in self.ours.databases
            if db["status"] == "ACTIVE"
            and self.covered(feature.applies_to, db["database_id"], db["name"])
        ]
        if not dbs:
            return
        common = dict(field=feature.feature, quote=feature.evidence_quote,
                      note=f"applies to: {feature.applies_to or 'all'}")  # fmt: skip
        if feature.feature == "engine_versions":
            theirs = {
                major_version(v)
                for v in (
                feature.value if isinstance(feature.value, list) else [feature.value]
            )
            }  # fmt: skip
            ours = set()
            for db in dbs:
                ours |= {major_version(v) for v in db["engine_versions"] or []}
            if ours != theirs:
                self.add(
                    page, "FEATURE_MISMATCH", "medium", "database",
                    ours=sorted(ours, key=lambda v: (len(v), v)),
                    theirs=sorted(theirs, key=lambda v: (len(v), v)), **common,
                )  # fmt: skip
            return
        try:
            theirs = float(feature.value)
        except (TypeError, ValueError):
            self.stats["db_features_unparsed"] += 1
            return
        values = Counter(db[column] for db in dbs)
        wrong = {v: n for v, n in values.items() if v is None or float(v) != theirs}
        if wrong:
            self.add(
                page, "FEATURE_MISMATCH", "medium", "database",
                ours={str(k): n for k, n in wrong.items()}, theirs=feature.value,
                **common,
            )  # fmt: skip

    # ##########################################################################
    # regions

    def compare_regions(self, page: SourcePage, regions):
        listed = set()
        for region in regions:
            self.stats["regions"] += 1
            region_id = self.ours.find_region(region.region) or self.ours.find_region(
                region.name
            )
            if region_id is None:
                self.add(
                    page, "MISSING_IN_DB", "low", "region", region=region.region,
                    theirs=region.name, quote=region.evidence_quote,
                    note="Region listed by the vendor but not among ours "
                    "(may be intentionally excluded, e.g. sovereign or China regions).",
                )  # fmt: skip
                continue
            listed.add(region_id)
        self.seen_regions |= listed

    # ##########################################################################
    # completeness checks across all pages

    def completeness(self, pages: List[Tuple[SourcePage, Extraction]]):
        spec_pages = [
            p
            for p, e in pages
            if p.complete and not p.region and PageKind.SERVER_SPECS in p.kinds
            and e.servers
        ]  # fmt: skip
        for server in self.ours.servers:
            if server["status"] != "ACTIVE" or server["server_id"] in self.seen_servers:
                continue
            # constrained vCPU sizes (e.g. Azure's Standard_E16-4ads_v5) are
            # documented separately as variants of their base size
            base_id = re.sub(r"(\d+)-\d+", r"\1", server["server_id"])
            if base_id != server["server_id"] and base_id in self.seen_servers:
                self.stats["constrained_variants_of_listed_sizes"] += 1
                continue
            for page in spec_pages:
                if self.covered(page.covers, server["server_id"], server["name"]):
                    self.add(
                        page, "NOT_AT_VENDOR", "high", "server",
                        sku=server["name"], our_id=server["server_id"],
                        note="Active in our data, but not listed on the vendor "
                        "pages marked complete for this SKU pattern.",
                    )  # fmt: skip
                    break

        server_by_id = {s["server_id"]: s for s in self.ours.servers}
        # pricing pages often leave out previous generation types
        previous_generation = {
            norm(spec.sku)
            for _, extraction in pages
            for spec in extraction.servers
            if spec.status == "previous_generation"
        }
        for page, extraction in pages:
            if not (page.complete and page.region and extraction.server_prices):
                continue
            region_id = self.ours.find_region(page.region)
            page_allocations = {pr.allocation for pr in extraction.server_prices}
            for (
                server_id,
                price_region,
            ), prices in self.ours.prices_by_server_region.items():
                if price_region != region_id:
                    continue
                server = server_by_id.get(server_id)
                if server and norm(server["name"]) in previous_generation:
                    self.stats["previous_generation_prices_skipped"] += 1
                    continue
                if server is None or not self.covered(
                    page.covers, server["server_id"], server["name"]
                ):
                    continue
                for allocation in {p["allocation"].lower() for p in prices}:
                    # only judge allocations the page covers
                    if allocation not in page_allocations:
                        continue
                    if (server_id, region_id, allocation) not in self.seen_prices:
                        self.add(
                            page, "NOT_AT_VENDOR", "medium", "server_price",
                            sku=server["name"], our_id=server_id, region=region_id,
                            field=f"{allocation} price",
                            ours=f"{min(p['price'] for p in prices):.6f} "
                            f"{prices[0]['currency']}",
                            note="We have a price in this region, but the vendor's "
                            "complete price list for the region does not include it.",
                        )  # fmt: skip

        db_pages = [
            p for p, e in pages
            if p.complete and PageKind.DB_SPECS in p.kinds and e.db_specs
        ]  # fmt: skip
        for db in self.ours.databases:
            if db["status"] != "ACTIVE" or db["database_id"] in self.seen_databases:
                continue
            for page in db_pages:
                if self.covered(page.covers, db["database_id"], db["name"]):
                    self.add(
                        page, "NOT_AT_VENDOR", "high", "database",
                        sku=db["name"], our_id=db["database_id"],
                        note="Active database SKU in our data, but not listed on "
                        "the vendor pages marked complete for this pattern.",
                    )  # fmt: skip
                    break

        region_pages = [p for p, e in pages if p.complete and e.regions]
        if region_pages:
            for region in self.ours.regions:
                if region["status"] == "ACTIVE" and (
                    region["region_id"] not in self.seen_regions
                ):
                    self.add(
                        region_pages[0], "NOT_AT_VENDOR", "medium", "region",
                        region=region["region_id"], ours=region["name"],
                        note="Active region in our data, not on the vendor's region list.",
                    )  # fmt: skip

    def flag_source_conflicts(self):
        """Spec mismatches where another official page agrees with our value."""
        for finding in self.findings:
            if finding.type != "SPEC_MISMATCH":
                continue
            key = (finding.our_id, finding.field)
            agreeing = self.agreements.get(key, set()) - {finding.page_id}
            agreeing &= self.authoritative_pages
            if not finding.spec_authority and not agreeing:
                if key not in self.checked_by_authority:
                    finding.severity = "low"
                    finding.note = (
                        "Only from a secondary source (e.g. a pricing data feed); "
                        "not confirmed by an authoritative page yet."
                    )
                continue
            if agreeing:
                finding.type = "SOURCE_CONFLICT"
                finding.severity = "low"
                finding.note = (
                    f"Our value matches {', '.join(sorted(agreeing))}; "
                    f"only {finding.page_id} differs."
                )

    def dedupe(self):
        merged: Dict[tuple, Finding] = {}
        for finding in self.findings:
            key = finding.key()
            if key in merged:
                if finding.page_id not in merged[key].also_on_pages:
                    merged[key].also_on_pages.append(finding.page_id)
            else:
                merged[key] = finding
        self.findings = list(merged.values())


def load_extractions(
    vendor_id: str, vendor: VendorSources, out_dir: Path
) -> List[Tuple[SourcePage, Extraction]]:
    pages = []
    for page in iter_pages(vendor, vendor_id, out_dir):
        path = extracted_dir(out_dir, vendor_id) / f"{page_slug(page.id)}.json"
        if path.exists():
            pages.append((page, Extraction.model_validate_json(path.read_text())))
    return pages


def compare_vendor(
    vendor_id: str,
    vendor: VendorSources,
    ours: Ours,
    out_dir: Path,
    price_tolerance: float = 0.01,
) -> Tuple[List[Finding], dict]:
    comparer = Comparer(vendor_id, vendor, ours, price_tolerance)
    pages = load_extractions(vendor_id, vendor, out_dir)
    comparer.stats["pages_with_extractions"] = len(pages)
    comparer.authoritative_pages = {p.id for p, _ in pages if p.spec_authority}
    # specs first so that SKU labels resolved by specs can be reused for prices
    for page, extraction in pages:
        for spec in extraction.servers:
            comparer.compare_server_spec(page, spec)
    for page, extraction in pages:
        for price in extraction.server_prices:
            comparer.compare_server_price(page, price)
        if extraction.component_rates:
            comparer.compare_component_rates(page, extraction.component_rates)
        for spec in extraction.db_specs:
            comparer.compare_db_spec(page, spec)
        for price in extraction.db_prices:
            comparer.compare_db_price(page, price)
        for feature in extraction.db_features:
            comparer.compare_db_feature(page, feature)
        if extraction.regions:
            comparer.compare_regions(page, extraction.regions)
    comparer.completeness(pages)
    comparer.flag_source_conflicts()
    comparer.dedupe()
    return comparer.findings, dict(comparer.stats)
