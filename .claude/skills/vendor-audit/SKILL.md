---
name: vendor-audit
description: Audit sc-crawler's ingested vendor data (server and database SKUs, specs, GPUs, CPUs, prices, regions, DB features) against official vendor pages. Use when asked to check, audit or validate vendor data, look for missing or made-up SKUs, or verify prices against vendor docs.
---

# Vendor data audit

Cross-check our published data (the sc-data SQLite dump) against **official vendor
pages only**. Never use third-party sites (comparison sites, blogs, Pulumi/Terraform
docs, Wikipedia, etc.) as evidence.

Division of labor:

- `sc-audit ...` (Python, deterministic; the `audit/` project in this repo) fetches and caches the pages,
  parses machine-readable vendor feeds, compares, and writes the report.
- You (and your subagents) only **extract structured rows from cached pages**,
  then **triage** the findings.

Module design, comparison rules and vendor quirks are documented in
`audit/README.md`; read it before changing the tool or triaging.
The source list is `audit/sources.yaml`. Arguments to this skill
may name vendors (e.g. `hcloud gcp`); default to all vendors.

## 1. Prepare

```sh
# latest data dump
cd ~/projects/sc-data && source .venv/bin/activate && sc-data download ~/downloads/sc-data-all.db
cd ~/projects/sc-crawler && source .venv/bin/activate
pip install -q -e "audit[testing]"   # once: installs the sc-audit command

OUT=audit-out/$(date +%F)
sc-audit fetch --out $OUT [--vendor X ...]   # official pages -> $OUT/pages/
sc-audit parse --out $OUT [--vendor X ...]   # JSON feeds, no LLM needed
sc-audit pending --out $OUT --json [--vendor X ...]  # pages left for you
```

Check the `fetch` summary table: report pages with HTTP errors or flagged as
likely JS-rendered to the user. Some vendors (UpCloud, Vultr marketing pages)
block automated clients: **do not try to work around bot protection** (no
spoofed user agents, no headless browsers). Ask the user how to proceed instead.

## 2. Extract (subagents)

Get the schema with `sc-audit schema`. Split the `pending` pages into
batches (one vendor per batch; at most ~10 pages or ~400k characters per batch,
e.g. split Azure's per-series pages), and start one `general-purpose` subagent
per batch in parallel, with the extraction brief below plus its list of pages
(each with `markdown`, `output`, `kinds`, `region`, `currency`, `notes`).

Do not give subagents any of our own data or findings: they must extract what
the page says, without being anchored on our values.

### Extraction brief (pass to every subagent verbatim, plus the schema)

> You extract structured data from official cloud vendor pages that were saved as
> Markdown files. For each assigned page, read the whole file with the Read tool
> (use offset/limit for large files; read every part), then write one JSON file to
> the given `output` path, matching the `Extraction` JSON schema. Set `vendor`,
> `page_id`, `extracted_at` (current UTC time, ISO 8601), and
> `extracted_by: "claude-code"`. Fill only the lists matching the page `kinds`:
> `server_specs`/`gpu`/`lifecycle` → `servers`, `server_prices` → `server_prices`,
> `component_rates` → `component_rates`, `db_specs` → `db_specs`, `db_prices` →
> `db_prices`, `db_features` → `db_features`, `regions` → `regions`.
>
> Rules:
> - Use only information on the page. Never fill values from memory or other
>   sources. If a value is not stated, leave it null. Never compute a value the
>   page does not state, except for the unit conversions below.
> - One row per SKU (and per region/allocation for prices) in every table on
>   the page; do not skip rows and do not summarize ranges.
> - `sku`: the exact API/instance type name if shown (e.g. `cx23`,
>   `Standard_D4s_v5`, `n2-standard-4`, `ecs.g7.xlarge`, `db.m6i.large`, `b3-8`),
>   otherwise the name as displayed.
> - `evidence_quote`: a short verbatim snippet (the table row or sentence, at most
>   300 characters) that supports the row.
> - Units: memory in GiB (treat RAM "GB" as GiB unless the page explicitly says
>   decimal GB); disks in GB as displayed (1 TB = 1000 GB); network in Gbps (the
>   maximum or "up to" value); `gpu_memory_total_gib` summed over all GPUs;
>   `cpu_speed_ghz` is the max/turbo clock.
> - Prices: net prices excluding VAT; Linux/no-license prices only (skip Windows,
>   SQL Server, reserved and savings plans); `allocation` is `spot` for
>   spot/preemptible prices; keep the `unit` as shown (`hour` or `month`; prefer
>   hourly if both are shown, never convert yourself); ISO currency code;
>   `region` as the vendor's region code if stated, else null (the page default
>   region applies).
> - Component rates (per vCPU, per GiB of memory, per GPU, per GiB of local SSD):
>   `sku_prefix` is the machine series prefix the rate applies to (e.g. `n2-`,
>   `c3d-`), or the database tier prefix (`target: database`, with `ha_level`
>   when the page distinguishes zonal and regional/HA rates).
> - Database prices: set `ha_level`, `ha_strategy`, `nodes` and `deployment` only
>   as stated on the page.
> - Database features: only explicit values (`sla` as a percentage number,
>   `max_read_replicas`, `continuous_backups_days` = maximum point-in-time
>   recovery window, `storage_extra_max_gb`, `engine_versions` = supported major
>   versions). Use `applies_to` (regex on SKU names) when a value only applies to
>   some tiers.
> - `status`: only when the page states it for the SKU or its family:
>   `unavailable` (currently not orderable, sold out, end of sale),
>   `previous_generation`, `retiring` (retirement announced) or `retired`;
>   otherwise null. Ignore availability notes shown identically for every SKU
>   (static placeholders of client-side availability checks).
> - Lifecycle pages: `servers` rows with `sku` and `status` (`previous_generation`,
>   `retiring`, `retired`) and nothing else, one row per size when sizes are listed,
>   otherwise one row per series with the series name as `sku`.
> - Regions: one row per region with the vendor's region code, name and zone count
>   if stated.
> - Put anything that limits the extraction (truncated tables, JS placeholders,
>   prices shown only for a different region or currency) in `notes`.
>
> After writing the files, run
> `sc-audit validate --out <OUT> --vendor <vendor>` and fix any errors.
> Reply with one line per page: page id, row counts, and notes.

## 3. Compare

```sh
sc-audit validate --out $OUT
sc-audit compare --out $OUT --db ~/downloads/sc-data-all.db
```

This writes `$OUT/report.md`, `findings.csv` and `findings.jsonl`. Re-run
`compare` for all vendors at the end, as each run overwrites the report.

## 4. Triage

Verdicts are persistent: they live in `audit/triage.yaml`
(version-controlled, applied on every `compare` run, format documented at the top
of the file and in the module README). Humans edit the same file. Never change or
remove entries written by a person (`by:` not starting with `claude`) without
asking; propose the change instead.

Only triage findings without a verdict (the `triage` column of `report.md` is
empty; untriaged rows are listed first). For every untriaged `high` finding (and a
sample of `medium` ones), open the cached Markdown page
(`$OUT/pages/<vendor>/<page>.md`) and decide:

- `confirmed`: the page clearly states a different value than ours;
- `false_positive`: the extraction or the comparison is wrong (also fix the
  extraction JSON if it misread the page, and re-run `compare`);
- `expected`: a known, accepted difference (by design or a modelling choice);
- `to_verify`: needs a check against the vendor API/console, e.g. two official
  sources disagree; say which.

For confirmed findings, look at the `code_hint` function in
`src/sc_crawler/vendors/_<vendor>.py` and name the likely cause (hardcoded table,
regex, unit conversion, price formula) in the `note`. Do not change ingest code as
part of the audit unless the user asks.

Add one entry per pattern (not per SKU when a regex covers them), with
`by: claude (...)` and today's `date`. Pin `ours`/`theirs` for false positives
tied to specific values, so they expire when the data changes. Put specific
entries before general ones (first match wins). Re-run `compare`, then review the
"Stale triage entries" section of `report.md`: stale entries usually mean a fix
landed or a page changed; propose removing them.

Free-form notes for a single run can go to `$OUT/notes.md` (included in
`report.md`). Finally, summarize the new confirmed issues for the user, most severe
first, with the counts of false positives per type.

## 5. Archive

```sh
sc-audit archive --out $OUT
```

This packs the run (pages, extractions, findings, config) into `$OUT.tar.xz` with a
manifest and verifies it. Tell the user to upload both the archive and
`$OUT.manifest.json` to the private `audit-runs/` folder (S3 or Google Drive, see
the README). Do not upload yourself. Set `evidence: audit-runs/<run>.tar.xz` on the
triage entries added in this run.

## Maintaining the sources

- `sc-audit seed-urls` lists vendor URLs cited in our code and docs that
  are not yet in `sources.yaml`.
- When a page is JS-rendered or moved, look for an official replacement with
  WebSearch restricted to the vendor's `allowed_domains`, and propose the
  `sources.yaml` change to the user.
- Mark pages `complete: true` only if they list every SKU matching `covers`;
  this drives the "not at vendor" (possibly made-up SKU) findings.
