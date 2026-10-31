"""Load our own records for a vendor from an sc-data SQLite dump (read-only)."""

import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# vendor-specific prefixes that are often omitted in vendor docs
SKU_PREFIXES = {
    "azure": ["standard"],
    "alicloud": ["ecs"],
}


def norm(text: Optional[str]) -> str:
    """Normalize a name for matching: lowercase alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def sku_keys(vendor: str, *names: Optional[str]) -> set:
    keys = set()
    for name in names:
        key = norm(name)
        if not key:
            continue
        keys.add(key)
        for prefix in SKU_PREFIXES.get(vendor, []):
            if key.startswith(prefix) and len(key) > len(prefix):
                keys.add(key[len(prefix) :])
    return keys


def _rows(conn: sqlite3.Connection, sql: str, *params) -> List[dict]:
    cursor = conn.execute(sql, params)
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _json(value):
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


@dataclass
class Ours:
    vendor: str
    servers: List[dict]
    server_prices: List[dict]
    databases: List[dict]
    database_prices: List[dict]
    regions: List[dict]
    zones: List[dict]
    ipv4_prices: Dict[str, dict] = field(default_factory=dict)
    server_index: Dict[str, List[dict]] = field(default_factory=dict)
    database_index: Dict[str, List[dict]] = field(default_factory=dict)
    region_index: Dict[str, str] = field(default_factory=dict)
    prices_by_server_region: Dict[tuple, List[dict]] = field(default_factory=dict)
    db_prices_by_db_region: Dict[tuple, List[dict]] = field(default_factory=dict)
    price_regions: Dict[str, set] = field(default_factory=dict)

    def __post_init__(self):
        for server in self.servers:
            names = (
                server["server_id"],
                server["name"],
                server["api_reference"],
                server["display_name"],
            )
            for key in sku_keys(self.vendor, *names):
                self.server_index.setdefault(key, []).append(server)
        for db in self.databases:
            names = (db["database_id"], db["name"], db["api_reference"])
            for key in sku_keys(self.vendor, *names):
                self.database_index.setdefault(key, []).append(db)
        # active regions first, as retired ones may list the same names as aliases
        for region in sorted(self.regions, key=lambda r: r["status"] != "ACTIVE"):
            names = [
                region["region_id"],
                region["name"],
                region["api_reference"],
                region["display_name"],
            ] + list(region["aliases"] or [])
            for name in names:
                if norm(name):
                    self.region_index.setdefault(norm(name), region["region_id"])
        prices = defaultdict(list)
        for price in self.server_prices:
            prices[(price["server_id"], price["region_id"])].append(price)
            self.price_regions.setdefault(price["server_id"], set()).add(
                price["region_id"]
            )
        self.prices_by_server_region = dict(prices)
        db_prices = defaultdict(list)
        for price in self.database_prices:
            db_prices[(price["database_id"], price["region_id"])].append(price)
        self.db_prices_by_db_region = dict(db_prices)

    def find_servers(self, sku: str) -> List[dict]:
        """Our servers matching a vendor SKU label, active ones first."""
        found = {}
        for key in sku_keys(self.vendor, sku):
            for server in self.server_index.get(key, []):
                found[server["server_id"]] = server
        return sorted(found.values(), key=lambda s: s["status"] != "ACTIVE")

    def find_databases(self, sku: str) -> List[dict]:
        found = {}
        for key in sku_keys(self.vendor, sku):
            for db in self.database_index.get(key, []):
                found[db["database_id"]] = db
        return sorted(found.values(), key=lambda d: d["status"] != "ACTIVE")

    def find_region(self, region: Optional[str]) -> Optional[str]:
        return self.region_index.get(norm(region)) if region else None

    def summary(self) -> str:
        return (
            f"{len(self.servers)} servers, {len(self.server_prices)} active server "
            f"prices, {len(self.databases)} databases, {len(self.database_prices)} "
            f"active database prices, {len(self.regions)} regions"
        )

    def to_dict(self, regions: Iterable[str]) -> dict:
        region_ids = {self.find_region(r) for r in regions}
        return {
            "vendor": self.vendor,
            "servers": self.servers,
            "server_prices": [
                p for p in self.server_prices if p["region_id"] in region_ids
            ],
            "databases": self.databases,
            "database_prices": [
                p for p in self.database_prices if p["region_id"] in region_ids
            ],
            "regions": self.regions,
            "zones": self.zones,
        }


SERVER_COLUMNS = """
    server_id, name, api_reference, display_name, family, series, status,
    vcpus, cpu_manufacturer, cpu_family, cpu_model, cpu_speed, cpu_allocation,
    memory_amount, accelerator_count, accelerator_model, accelerator_memory_total,
    storage_size, storage_type, network_speed_baseline, network_speed_max
"""

DATABASE_COLUMNS = """
    database_id, name, api_reference, display_name, family, series, server_id, status,
    vcpus, memory_amount, storage_size, storage_extra_max, engine_versions, ha,
    ha_strategy, max_read_replicas, continuous_backups, scheduled_backups, sla
"""


def load_ours(db_path: Path, vendor: str) -> Ours:
    """Read our records of a vendor. Prices are limited to active ones."""
    uri = f"file:{Path(db_path).expanduser()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        servers = _rows(
            conn, f"SELECT {SERVER_COLUMNS} FROM server WHERE vendor_id = ?", vendor
        )
        server_prices = _rows(
            conn,
            "SELECT server_id, region_id, zone_id, operating_system, allocation, "
            "unit, price, price_tiered, currency FROM server_price "
            "WHERE vendor_id = ? AND status = 'ACTIVE'",
            vendor,
        )
        databases = _rows(
            conn,
            f"SELECT {DATABASE_COLUMNS} FROM database WHERE vendor_id = ?",
            vendor,
        )
        database_prices = _rows(
            conn,
            "SELECT database_id, region_id, allocation, ha, ha_strategy, unit, price, "
            "currency FROM database_price WHERE vendor_id = ? AND status = 'ACTIVE'",
            vendor,
        )
        regions = _rows(
            conn,
            "SELECT region_id, name, api_reference, display_name, aliases, status "
            "FROM region WHERE vendor_id = ?",
            vendor,
        )
        ipv4_prices = _rows(
            conn,
            "SELECT region_id, unit, price, currency FROM ipv4_price "
            "WHERE vendor_id = ? AND status = 'ACTIVE'",
            vendor,
        )
        zones = _rows(
            conn,
            "SELECT region_id, zone_id, name, status FROM zone WHERE vendor_id = ?",
            vendor,
        )
    for row in databases:
        for key in ("engine_versions", "ha", "ha_strategy"):
            row[key] = _json(row[key])
    for row in regions:
        row["aliases"] = _json(row["aliases"])
    for row in server_prices:
        row["price_tiered"] = _json(row["price_tiered"])
    # zone-level prices are the same within a region in most cases: dedupe
    seen, deduped = set(), []
    for price in server_prices:
        key = (
            price["server_id"],
            price["region_id"],
            price["operating_system"],
            price["allocation"],
            price["unit"],
            price["currency"],
            round(price["price"], 6),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(price)
    return Ours(
        vendor,
        servers,
        deduped,
        databases,
        database_prices,
        regions,
        zones,
        ipv4_prices={row["region_id"]: row for row in ipv4_prices},
    )
