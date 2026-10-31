"""Persistent, human-editable verdicts on audit findings.

Triage entries live in `audit/triage.yaml` (version-controlled next to
`sources.yaml`) and are applied on every `compare` run, so a finding reviewed
once (e.g. marked as a false positive) is not reported as new again.

An entry matches a finding if all of its given criteria match. Pin `ours`
and/or `theirs` to make the verdict expire when either value changes.
"""

import datetime as dt
import re
from pathlib import Path
from typing import List, Literal, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field

from . import PROJECT_ROOT
from .compare import Finding

DEFAULT_TRIAGE = PROJECT_ROOT / "triage.yaml"

# verdicts hiding the finding from the main report (kept in findings.csv/jsonl)
SUPPRESSED = {"false_positive", "expected"}


class TriageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor: str
    type: Optional[str] = Field(
        default=None, description="Finding type, e.g. SPEC_MISMATCH."
    )
    field: Optional[str] = Field(
        default=None, description="Finding field, e.g. memory_gib."
    )
    match: Optional[str] = Field(
        default=None,
        description="Regex (full match) on our id or the vendor SKU.",
    )
    region: Optional[str] = None
    page: Optional[str] = Field(default=None, description="Regex on the page id.")
    ours: Optional[str] = Field(
        default=None, description="Pin our value (as shown in the report)."
    )
    theirs: Optional[str] = Field(
        default=None, description="Pin the vendor's value (as shown in the report)."
    )
    verdict: Literal["confirmed", "false_positive", "expected", "to_verify"]
    note: str
    issue: Optional[str] = Field(default=None, description="Issue or PR URL.")
    evidence: Optional[str] = Field(
        default=None,
        description="Archived run with the source pages, e.g. 'audit-runs/2026-10-31.tar.xz'.",
    )
    by: Optional[str] = None
    date: Optional[dt.date] = None

    def matches(self, finding: Finding) -> bool:
        if self.vendor != finding.vendor:
            return False
        if self.type and self.type != finding.type:
            return False
        if self.field and self.field != finding.field:
            return False
        if self.region and self.region != finding.region:
            return False
        if self.page and not re.search(self.page, finding.page_id):
            return False
        if self.match and not any(
            re.fullmatch(self.match, str(value))
            for value in (finding.our_id, finding.sku)
            if value is not None
        ):
            return False
        if self.ours is not None and self.ours != _shown(finding.ours):
            return False
        if self.theirs is not None and self.theirs != _shown(finding.theirs):
            return False
        return True


def _shown(value) -> str:
    """Values as compared by `ours`/`theirs` pins: plain strings, numbers without trailing .0."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def load_triage(path: Optional[Path] = None) -> List[TriageEntry]:
    source = Path(path) if path else DEFAULT_TRIAGE
    if not source.exists():
        return []
    data = yaml.safe_load(source.read_text()) or {}
    entries = [TriageEntry.model_validate(entry) for entry in data.get("entries", [])]
    for entry in entries:
        for pattern in (entry.match, entry.page):
            if pattern:
                re.compile(pattern)
    return entries


def apply_triage(
    findings: List[Finding], entries: List[TriageEntry], vendors: List[str]
) -> Tuple[List[Finding], List[TriageEntry]]:
    """Set the verdict of matching findings (first matching entry wins).

    Returns the findings and the stale entries of the compared vendors,
    i.e. entries not matching any finding anymore (fixed, or the page changed).
    """
    used = set()
    for finding in findings:
        for i, entry in enumerate(entries):
            if entry.matches(finding):
                finding.verdict = entry.verdict
                finding.triage_note = entry.note
                finding.triage_issue = entry.issue
                used.add(i)
                break
    stale = [
        entry
        for i, entry in enumerate(entries)
        if i not in used and entry.vendor in vendors
    ]
    return findings, stale
