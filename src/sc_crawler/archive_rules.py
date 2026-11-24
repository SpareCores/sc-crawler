"""Archive rules: the records replaced by another record or deliberately dropped.

A record gets the [ARCHIVED][sc_crawler.table_fields.Status] status only
through the [archive_rules][sc_crawler.archive_rules.archive_rules] listed
here, which are applied by the `pull` and `sync` commands on every run:

- Each old → new pair is one [ArchiveRule][sc_crawler.tables.ArchiveRule]:
  a rename or re-key is one rule, a split is one rule per successor with
  the same `match`, a merge is one rule per old record with the same
  `successor`. A dropped record has one rule with an empty `successor`
  and a `reason`.
- `match` is the primary key of the record to archive, or a subset of its
  columns to archive every record with those values (a dict column such as
  `config` matches only when the whole dict is equal). `successor` gives
  the new values of the same columns. Give enum columns by the value of the
  member (e.g. `spot` for `allocation`), not by its name as stored in the
  database (`SPOT`).
- Child records, i.e. records referencing an archived record in their
  primary key (e.g. the zones and prices of a region, or the scores of a
  benchmark), are archived as well without their own rules. Add a rule
  for a child record only when its successor does not follow from the
  rules of its parents (e.g. the Hetzner zones below).
- Never remove a rule that has archived records. Rules removed from here
  are kept as `INACTIVE` in the `archive_rule` table.

The methods matching and applying the rules are on
[ScModel][sc_crawler.table_bases.ScModel] and
[ArchiveRule][sc_crawler.tables.ArchiveRule], e.g.
[archived_by][sc_crawler.table_bases.ScModel.archived_by] tracing which rules
archived a record.

Use `ARCHIVED` only for our own decisions about the identity of a record,
see [Status][sc_crawler.table_fields.Status] on how it differs from
`INACTIVE` and `RETIRED`.
"""

from typing import List

from .tables import ArchiveRule

# Region (and zone) ids from the deprecated Hetzner /v1/datacenters endpoint,
# mapped to the location names used as region ids since v0.10.1.
_HCLOUD_DATACENTER_TO_LOCATION = {
    "2": "nbg1",
    "3": "hel1",
    "4": "fsn1",
    "5": "ash",
    "6": "hil",
    "7": "sin",
}
_HCLOUD_REASON = (
    "Hetzner deprecated the datacenters API endpoint, "
    "so the location names replaced the datacenter ids."
)

# GCP machine type ids of the deprecated machine types mapped to the ids of
# their `deprecated.replacement` in the machineTypes API. The N1 memory-optimized
# types are documented aliases of the M1 ones: "The machines themselves did not
# change and the former names are still supported as aliases for these machines."
# (https://docs.cloud.google.com/compute/docs/memory-optimized-machines and
# https://cloud.google.com/products/compute/pricing/memory-optimized). The Z3
# renames are not documented, but the replacements have the same vCPUs, memory,
# local SSDs (12 x 3,000 GiB) and prices in all zones (checked in Nov 2026).
_GCP_RENAMED_MACHINE_TYPES = {
    "9096": "9196",  # n1-megamem-96 -> m1-megamem-96
    "10040": "11040",  # n1-ultramem-40 -> m1-ultramem-40
    "10080": "11080",  # n1-ultramem-80 -> m1-ultramem-80
    "10160": "11160",  # n1-ultramem-160 -> m1-ultramem-160
    "1742000": "1742013",  # z3-highmem-88 -> z3-highmem-88-highlssd
    "1742001": "1742018",  # z3-highmem-176 -> z3-highmem-176-standardlssd
}

archive_rules: List[ArchiveRule] = [
    *[
        ArchiveRule(
            table_name="region",
            match={"vendor_id": "hcloud", "region_id": old},
            successor={"vendor_id": "hcloud", "region_id": new},
            reason=_HCLOUD_REASON,
        )
        for old, new in _HCLOUD_DATACENTER_TO_LOCATION.items()
    ],
    # zones would be archived as children of their region as well, but the
    # zone ids reuse the region ids, so their successors need their own rules
    *[
        ArchiveRule(
            table_name="zone",
            match={"vendor_id": "hcloud", "region_id": old, "zone_id": old},
            successor={"vendor_id": "hcloud", "region_id": new, "zone_id": new},
            reason=_HCLOUD_REASON,
        )
        for old, new in _HCLOUD_DATACENTER_TO_LOCATION.items()
    ],
    *[
        ArchiveRule(
            table_name="server",
            match={"vendor_id": "gcp", "server_id": old},
            successor={"vendor_id": "gcp", "server_id": new},
            reason=(
                "Same machine as its successor: GCP renamed it and keeps "
                "the old name as an alias."
            ),
        )
        for old, new in _GCP_RENAMED_MACHINE_TYPES.items()
    ],
    ArchiveRule(
        table_name="benchmark",
        match={"benchmark_id": "app:static_web"},
        successor={"benchmark_id": "static_web:rps"},
        reason="Replaced by the benchmarks of the static_web framework.",
    ),
]
"""All archive rules, applied by the `pull` and `sync` commands."""
