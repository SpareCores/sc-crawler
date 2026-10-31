"""Write audit findings as JSON Lines, CSV and a Markdown report."""

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from .compare import Finding
from .triage import SUPPRESSED, TriageEntry

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
TOP_N = 25


def _cell(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, default=str)
    value = value.replace("|", "\\|").replace("\n", " ")
    return value if len(value) <= 120 else value[:117] + "..."


def _triage_cell(finding: Finding) -> str:
    if not finding.verdict:
        return ""
    text = finding.verdict
    if finding.triage_issue:
        text += f" ([issue]({finding.triage_issue}))"
    return text


def _db_metadata(db: Path) -> Dict[str, str]:
    try:
        uri = f"file:{Path(db).expanduser()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            return dict(conn.execute("SELECT key, value FROM _metadata").fetchall())
    except sqlite3.Error:
        return {}


def write_report(
    findings: List[Finding],
    stats: Dict[str, dict],
    out_dir: Path,
    db: Path,
    generated_at: datetime,
    stale: List[TriageEntry] = (),
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    findings = sorted(
        findings,
        key=lambda f: (
            f.vendor,
            SEVERITY_ORDER[f.severity],
            f.type,
            f.field or "",
            f.sku or "",
        ),
    )

    with open(out_dir / "findings.jsonl", "w") as fh:
        for finding in findings:
            fh.write(json.dumps(finding.to_dict(), default=str) + "\n")
    with open(out_dir / "findings.csv", "w", newline="") as fh:
        rows = [f.to_dict() for f in findings]
        if rows:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        k: v
                        if isinstance(v, (str, int, float, type(None)))
                        else json.dumps(v, default=str)
                        for k, v in row.items()
                    }
                )

    meta = _db_metadata(db)
    lines = [
        "# Vendor data audit",
        "",
        f"- Generated at: {generated_at.isoformat(timespec='seconds')}",
        f"- Audited data: `{db}` (published at {meta.get('published_at', '?')}, "
        f"sc-crawler {meta.get('sc_crawler_version', '?')})",
        "- Sources: official vendor pages only, see `pages/` for the snapshots. "
        "Findings from sources our ingest also reads are marked as not independent.",
        "",
        "## Summary",
        "",
        "| vendor | high | medium | low | info | suppressed by triage | pages extracted |",
        "|---|---|---|---|---|---|---|",
    ]
    by_vendor = defaultdict(list)
    suppressed = defaultdict(list)
    for finding in findings:
        if finding.verdict in SUPPRESSED:
            suppressed[finding.vendor].append(finding)
        else:
            by_vendor[finding.vendor].append(finding)
    for vendor in sorted(stats):
        counts = Counter(f.severity for f in by_vendor[vendor])
        lines.append(
            f"| {vendor} | {counts['high']} | {counts['medium']} | {counts['low']} "
            f"| {counts['info']} | {len(suppressed[vendor])} "
            f"| {stats[vendor].get('pages_with_extractions', 0)} |"
        )

    for vendor in sorted(stats):
        vendor_findings = by_vendor[vendor]
        lines += ["", f"## {vendor}", ""]
        lines.append(
            "Compared: "
            + ", ".join(f"{k}={v}" for k, v in sorted(stats[vendor].items()))
        )
        if not vendor_findings:
            lines += ["", "No findings."]
            continue
        groups = defaultdict(list)
        for finding in vendor_findings:
            if finding.severity == "info":
                continue
            groups[(finding.type, finding.field or "")].append(finding)
        lines += [
            "",
            "| severity | type | field | count | confirmed | to verify | untriaged |",
            "|---|---|---|---|---|---|---|",
        ]
        for (type_, field), group in sorted(
            groups.items(),
            key=lambda kv: (SEVERITY_ORDER[kv[1][0].severity], -len(kv[1])),
        ):
            verdicts = Counter(f.verdict for f in group)
            lines.append(
                f"| {group[0].severity} | {type_} | {field} | {len(group)} "
                f"| {verdicts['confirmed']} | {verdicts['to_verify']} "
                f"| {verdicts[None]} |"
            )
        info = [f for f in vendor_findings if f.severity == "info"]
        if info:
            lines.append(
                f"\nPlus {len(info)} info-level findings (values the vendor publishes "
                "but we don't have), see `findings.csv`."
            )
        for (type_, field), group in sorted(
            groups.items(),
            key=lambda kv: (SEVERITY_ORDER[kv[1][0].severity], -len(kv[1])),
        ):
            lines += [
                "",
                f"### {group[0].severity}: {type_} {field} ({len(group)})",
                "",
                f"Code to check: `{group[0].code_hint}`",
                "",
                "| sku | our id | region | ours | theirs | diff % | page | evidence "
                "| triage |",
                "|---|---|---|---|---|---|---|---|---|",
            ]
            # untriaged first, as these need attention
            group = sorted(group, key=lambda f: f.verdict is not None)
            for f in group[:TOP_N]:
                page = f.page_id + (" (data feed)" if f.feed else "")
                page += "" if f.independent else " (not independent)"
                lines.append(
                    f"| {_cell(f.sku)} | {_cell(f.our_id)} | {_cell(f.region)} "
                    f"| {_cell(f.ours)} | {_cell(f.theirs)} | {_cell(f.diff_pct)} "
                    f"| [{_cell(page)}]({f.url}) | {_cell(f.quote or f.note)} "
                    f"| {_triage_cell(f)} |"
                )
            if len(group) > TOP_N:
                lines.append(f"\n... and {len(group) - TOP_N} more in `findings.csv`.")

    if any(suppressed.values()):
        lines += [
            "",
            "## Suppressed by triage",
            "",
            "Findings marked as `false_positive` or `expected` in `triage.yaml` "
            "(still listed in `findings.csv`).",
            "",
            "| vendor | type | field | verdict | count | note |",
            "|---|---|---|---|---|---|",
        ]
        for vendor in sorted(suppressed):
            groups = Counter(
                (f.type, f.field or "", f.verdict, f.triage_note)
                for f in suppressed[vendor]
            )
            for (type_, field, verdict, note), n in sorted(groups.items()):
                lines.append(
                    f"| {vendor} | {type_} | {field} | {verdict} | {n} | {_cell(note)} |"
                )

    if stale:
        lines += [
            "",
            "## Stale triage entries",
            "",
            "Entries in `triage.yaml` not matching any finding anymore: fixed, or the "
            "values/pages changed. Review and remove them.",
            "",
            "| vendor | type | field | match | verdict | note |",
            "|---|---|---|---|---|---|",
        ]
        for e in stale:
            lines.append(
                f"| {e.vendor} | {e.type or ''} | {e.field or ''} | {_cell(e.match)} "
                f"| {e.verdict} | {_cell(e.note)} |"
            )

    # free-form notes of this run (persistent verdicts belong to triage.yaml)
    notes = out_dir / "notes.md"
    if notes.exists():
        lines += ["", notes.read_text().strip()]

    path = out_dir / "report.md"
    path.write_text("\n".join(lines) + "\n")
    return path
