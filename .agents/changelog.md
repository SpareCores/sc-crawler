# Changelog rules

Rules for writing the root `CHANGELOG.md`, published as the
[crawler changelog](https://docs.sparecores.com/crawler/news). Readers are developers who
use the `sparecores-crawler` package, its database schema or the published data (e.g.
through the [Spare Cores API](https://docs.sparecores.com/api/news)); they want to know
what changed in the tables, columns, records, CLI and Python API they depend on.

## Releases

- Each release has its own section, newest first: `## vX.Y.Z (Month D, YYYY)`, with the
  full month name and the day without a leading zero, e.g. `## v0.12.0 (November 21,
  2026)` or `## v0.6.0 (June 3, 2026)`.
- Add each change in the same PR, under the `## vX.Y.x (DEVELOPMENT)` section of the
  next release; create the section if it is missing. When releasing, rename it to the
  release heading (see "Production and releases" in `AGENTS.md`).
- A release heading is also its anchor on the docs site, which the
  [API changelog](https://docs.sparecores.com/api/news) (`sc-keeper`) links to, e.g.
  `#v0120-november-21-2026`. Don't change a published heading; if one must change,
  update the links to it in the same change.

## What to include

- Every change that users of the package, the schema or the data notice: new vendors,
  benchmarks, tables, columns and CLI commands, changed values, statuses and units of
  existing records, schema changes, and new minimum versions.
- Internal changes that maintainers need to know about (refactors of vendor modules,
  inventory order, test and tooling changes) go under `Maintenance:`.
- Describe the net change of a batch of related work, not each commit.

## Subsections

- Use these subsections in this order and omit empty ones. Keep the headings exactly as
  written, in the plural even for a single entry, so the file stays easy to parse:
  - `Breaking changes:`
  - `New vendors:`
  - `New benchmarks:`
  - `New features:`
  - `Improvements:`
  - `Fixes:`
  - `Maintenance:`
  - `Database migrations:`
- A breaking change can break existing users of the package or the data: a removed,
  renamed or retyped table, column, enum value, JSON field or `benchmark_id`, a changed
  primary key, record id, unit or meaning, a new minimum Python version, or a change to
  the Python API or CLI. State what to use instead.
- New columns and fields are `New features:`; better data for existing records (more
  vendors filled, more accurate values) is `Improvements:`; wrong data or crashes put
  right are `Fixes:`.
- `Database migrations:` lists the DDL changes of each release with a migration: tables
  and columns, including the `_scd` tables, and enum changes. The feature entry notes
  whether the migration backfills existing rows or only the next inventory refresh does.

## Entries

- Describe what users get now, not how it was implemented. Write each entry as a noun
  phrase or in the present tense; do not start it with a verb in any tense (`Add`,
  `Added`, `Fix`, `Fixed`, `Rename`, `Support`, `Update`). `Database migrations:` entries
  are the exception: they start with the DDL verb (`Add the ... column to the ... table`).
  - New feature: `` `Server.retirement_date` and `Database.retirement_date`: the
    retirement date announced by the vendor (#195) ``
  - Fix: `` `upcloud`: plans on the `hdd` (Archive) storage tier have the `HDD` storage
    type (was `SSD`) (#182) ``, not `Fix the storage type of …`
- Start a vendor-specific entry with the backticked vendor ID and a colon, e.g.
  `` `gcp`: ``, `` `azure`: ``, `` `alicloud`: ``, never the vendor name (`Azure`,
  `Alibaba Cloud`). Entries under `New vendors:` name the vendor and give its ID, e.g.
  `` Oracle Cloud Infrastructure (`oci`) ``.
- Be specific: name the tables, columns, enum values, server types and commands in
  backticks, and give an example record when it helps (`` e.g. `p5.48xlarge` ``).
- End each entry with the PR number(s) when there is a PR, e.g. `(#123)` or
  `(#12, #15)`; no trailing period.

## Formatting

- Wrap entries at about 80 characters and indent continuation lines by two spaces.

## References

- GitLab, [Changelog entries](https://docs.gitlab.com/development/changelog/): describe
  the change by its effect on the reader, not its implementation.
- Google developer documentation style guide,
  [Present tense](https://developers.google.com/style/tense) and
  [Timeless documentation](https://developers.google.com/style/timeless-documentation):
  prefer the present tense; time-bound wording is fine in release notes.
