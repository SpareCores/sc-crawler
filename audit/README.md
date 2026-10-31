# `sc-crawler-audit`: vendor data audit

Cross-checks the data published by sc-crawler (the sc-data SQLite dump) against
**official vendor sources only**, to find:

- SKUs we are missing, or SKUs we list that the vendor does not (made up by the ingest, or retired);
- wrong specs: vCPUs, memory, GPU count/model/memory, CPU model, local storage, network;
- wrong prices, including prices we calculate from per-vCPU/GiB/GPU components;
- wrong statuses (active vs retiring/retired), regions and database features (SLA, replicas, backups, versions).

The tool reports findings with evidence. It does not change ingest code or data.

This is a separate, **unpublished** Python project living next to the crawler (`audit/`, with its
own `pyproject.toml`, marked `Private :: Do Not Upload`). It is not part of the
`sparecores-crawler` package: it reads the published SQLite dump, not crawler objects, and stays in
this repo because its findings point at crawler code (`code_hint`, `seed-urls`, fixes and their
triage entries can land in one commit).

## Setup

From the repo root, in the crawler's virtualenv:

```sh
pip install -e "audit[testing]"   # or: uv pip install -e "audit[testing]"
sc-audit --help
cd audit && pytest                # tests
```

Run `sc-audit` from the repo root: run outputs go to `audit-out/` (git-ignored) and
`seed-urls` scans the crawler sources under `src/`.

## Workflow

```
sc-data download ──────────────────────► sc-data-all.db (read-only)
sources.yaml ──► audit fetch ──► <out>/pages/<vendor>/<page>.{html|json, md, meta.json}
                 audit parse ──► <out>/extracted/<vendor>/<page>.json   (machine-readable feeds)
     Claude Code subagents ────► <out>/extracted/<vendor>/<page>.json   (all other pages)
                 audit validate
     triage.yaml ─► audit compare ─► <out>/findings.{jsonl,csv}, <out>/report.md
```

1. **Fetch** (`fetch.py`): downloads each page in `sources.yaml`, rejects hosts outside the
   vendor's `allowed_domains`, stores the raw response, a Markdown rendering and metadata
   (final URL, status, sha256, timestamp), and discovers child pages (`follow`).
2. **Extract**: deterministic parsers (`parsers.py`) for JSON feeds; for everything else,
   Claude Code subagents read the cached Markdown and write JSON matching `schema.Extraction`
   (see the skill at `.claude/skills/vendor-audit/SKILL.md`, which holds the extraction brief).
3. **Compare** (`compare.py`, `export.py`): all matching, unit conversions and tolerances are
   deterministic Python. Our data is read directly from the SQLite dump.
4. **Report and triage** (`report.py`, `triage.py`): Markdown summary plus every finding in
   JSONL/CSV. Verdicts from `triage.yaml` (written by humans or the skill) are applied on every
   run; see [Triage](#triage).

The usual entry point is the Claude Code skill (`/vendor-audit [vendors]`), which runs all of
the above, including the subagents and triage.

## CLI

All `sc-audit` commands take `--out` (default `audit-out/<today>`), `--vendor`/`--exclude-vendor`
(repeatable) and `--sources` (another YAML instead of the bundled `sources.yaml`).

| command | what it does |
|---|---|
| `sc-audit fetch [--page REGEX] [--cache-ttl H] [--dry-run]` | download pages and discovered child pages; prints HTTP errors, "JS-rendered?" (tiny Markdown) and "no tables" flags |
| `sc-audit parse` | run deterministic parsers on fetched feeds |
| `sc-audit pending [--json]` | pages fetched but not yet extracted, with paths for the subagents |
| `sc-audit schema` | JSON schema of extraction files |
| `sc-audit validate` | validate extraction files |
| `sc-audit export --db PATH` | dump our records as used by the comparison (for inspection) |
| `sc-audit compare --db PATH [--price-tolerance 0.01] [--triage PATH]` | compare, apply `triage.yaml`, write findings and `report.md` |
| `sc-audit seed-urls` | list vendor URLs cited in our code/docs that are not in `sources.yaml` yet |
| `sc-audit archive [--output PATH]` | pack a run into `<run>.tar.xz` plus `<run>.manifest.json`, then verify it (see [Archiving runs](#archiving-runs)) |
| `sc-audit verify-archive PATH` | check a (downloaded) archive against its manifest |

`--db` defaults to `~/downloads/sc-data-all.db`. Get the latest dump with
`sc-data download ~/downloads/sc-data-all.db` (from the sc-data repo).


## Files

| file | purpose |
|---|---|
| `sources.yaml` | the official pages per vendor, with what each page is authoritative for |
| `triage.yaml` | persistent verdicts on findings (human-editable) |
| `schema.py` | pydantic models: source list and extraction rows (fixed units) |
| `sources.py` | load/validate sources, domain allowlist, page ids, page traversal |
| `fetch.py` | download, HTML to Markdown, link discovery |
| `parsers.py` | parsers for AWS EC2/RDS/spot pricing feeds and the Alibaba ECS price list |
| `export.py` | read our records from SQLite, name/region indexes |
| `compare.py` | all checks, finding types, severities |
| `report.py` | JSONL/CSV/Markdown output |
| `triage.py` | load and apply `triage.yaml` |
| `seed.py` | collect vendor URLs cited in the repo |
| `archive.py` | pack/verify runs for long-term storage |
| `cli.py` | the `sc-audit` Typer app |

Code is in `src/sc_crawler_audit/`, tests in `tests/test_audit.py` (all paths relative to `audit/`).

## `sources.yaml`

Per vendor:

- `allowed_domains`: first-party domains only, subdomains included. URLs and redirects outside them are rejected.
- `reference_regions`: used by `export`.
- `hours_per_month`: for converting monthly prices (default 730).
- `monthly_price_is_cap`: monthly prices are a cap of hourly billing (e.g. Hetzner), compared with our `price_tiered` cap.

Per page:

| field | meaning |
|---|---|
| `id`, `url` | page id (used in file names) and URL |
| `kinds` | what the page is authoritative for: `server_specs`, `server_prices`, `component_rates`, `gpu`, `db_specs`, `db_prices`, `db_features`, `regions`, `lifecycle`, `index` (navigation only, never extracted) |
| `covers` | regex on our SKU ids/names the page is responsible for |
| `complete` | the page lists **all** SKUs matching `covers`; drives `NOT_AT_VENDOR`. With `region` set, this applies to the prices in that region; otherwise to specs |
| `region`, `currency` | defaults for prices shown without them |
| `independent` | `false` if our ingest reads the very same source |
| `spec_authority` | `false` for secondary spec sources (e.g. pricing feeds); their spec mismatches need confirmation by an authoritative page |
| `prices_include_ipv4` | listed prices include a public IPv4 (our IPv4 price is added before comparing) |
| `implies_availability` | `false` for generic price lists that cover SKU/region pairs which may not be sold |
| `parser` | name of a deterministic parser in `parsers.PARSERS` |
| `follow` | discover child pages: `pattern` (regex on absolute URLs), `kinds`, `covers`, `complete`, `max_pages`, `recursive` |

Child pages get ids like `<parent id>/<url slug>`. Pages are visited breadth-first, in the same
order in `fetch` and `iter_pages`, so a page linked from several parents always gets the same id.

## Extraction schema (units)

All rows carry an `evidence_quote` (verbatim snippet from the page). Units are fixed regardless of
how the vendor shows them:

- memory in GiB;
- disks in GB (1 TB = 1000 GB; GiB values ×1.073741824);
- network in Gbps (max/"up to");
- GPU memory summed over all GPUs;
- prices with an explicit `unit` (`hour`/`month`, never converted by the extractor) and `currency`.

Values the page does not state are `null`; the extractor must not compute or infer them.

## Comparison

**SKU matching.** Names are compared case- and separator-insensitively against our `server_id`,
`name`, `api_reference` and `display_name`. Vendor prefixes are optional (`Standard_` for Azure,
`ecs.` for Alibaba). When a page shows no API names (e.g. "2 vCPU / 4 GB" plans), SKUs are
matched by specs (vCPUs, memory, storage, GPUs) if exactly one active SKU fits.

**Region matching.** Region ids, names, display names and aliases are matched, preferring active
regions (retired regions may carry current names as aliases). Prices in regions that are inactive
in our data are skipped.

**Finding types:**

| type | meaning |
|---|---|
| `SPEC_MISMATCH` | a spec differs beyond tolerance (exact for vCPUs; 1% for memory, storage, network and GPU count; 5% for GPU memory). CPU models are compared only by model number, as vendors often name the generation instead |
| `SOURCE_CONFLICT` | a spec mismatch where another authoritative official page agrees with our value (e.g. pricing feed vs docs) |
| `VALUE_MISSING_IN_DB` | the vendor states a value we don't have (info) |
| `MISSING_IN_DB` | the vendor lists a SKU we don't have |
| `NOT_AT_VENDOR` | an active SKU, price (per region) or region of ours that is absent from pages marked `complete`; possibly made up or retired. Constrained vCPU variants of listed sizes (Azure `E16-4ads_v5`) and previous-generation types on price pages are excluded |
| `STATUS_MISMATCH` | e.g. active in our data but retiring/retired at the vendor; retired expects `RETIRED`, retiring expects `PLANNED_FOR_RETIREMENT` or `RETIRED`. A retired series is mapped to our servers of that family |
| `PRICE_MISMATCH` | outside `--price-tolerance` (default 1%; 25% for spot); monthly prices compared via our monthly cap or `hours_per_month` |
| `PRICE_MISSING_IN_DB` | the vendor prices a SKU in a region where we have no price |
| `COMPONENT_PRICE_MISMATCH` | our price vs the vendor's per-vCPU/GiB/GPU/SSD rates × our specs (servers, or databases with `target: database`) |
| `FEATURE_MISMATCH` | database SLA, max read replicas, PITR days, max storage, major versions |

Severity: `high` for vCPUs, memory, GPUs, made-up SKUs and price differences >5%; `medium` for
other price, status and storage issues; `low` for network, storage type, CPU model, spot prices
and unconfirmed secondary-source findings; `info` for values we don't have.

Status, missing-price and not-at-vendor findings list **our active price regions**, because our
status is aggregated over all regions while a page may cover only some of them.

Identical findings from several pages are merged (`also_on_pages`).

## Triage

`triage.yaml` holds verdicts on findings and is version-controlled, so reviews survive runs and
are shared. Every `compare` run applies it (`--triage` to use another file). Each finding gets
the verdict of the first matching entry:

```yaml
entries:
  - vendor: gcp                  # required
    type: SPEC_MISMATCH          # optional criteria, all must match:
    field: memory_gib            #   type, field, region,
    match: "db-f1-micro"         #   match: regex (full match) on our id or the vendor SKU,
    ours: "0.599609375"          #   page: regex on the page id,
    theirs: "0.614"              #   ours/theirs: pin values as shown in the report
    verdict: false_positive      # confirmed | false_positive | expected | to_verify
    note: "Docs say 0.614 GB, which is 0.6 GiB."
    issue: https://github.com/SpareCores/sc-crawler/issues/...   # optional
    evidence: audit-runs/2026-10-31.tar.xz                       # optional: archived run
    by: daroczig                 # optional; the skill uses "claude (...)"
    date: 2026-10-31             # optional
```

- `false_positive` and `expected` findings are left out of the main report and counted in
  "Suppressed by triage" (they stay in `findings.csv`/`findings.jsonl` with their verdict).
- `confirmed` and `to_verify` findings stay in the report, with the verdict in the `triage`
  column; untriaged findings are listed first.
- Pin `ours`/`theirs` when a verdict only holds for specific values: when either value changes,
  the entry stops matching and the finding is reported again.
- Entries not matching any finding are listed as **stale** in the report: usually a fix landed
  or a page changed. Review and remove them.
- Put specific entries before general ones; the first match wins.

## Design decisions

- **The LLM only extracts; Python compares.** Comparisons, conversions and tolerances are
  deterministic and testable. Extraction subagents never see our data, so they cannot anchor on it.
- **Claude Code, not the API.** Extraction and triage run as a Claude Code skill on the user's
  subscription; no `anthropic` dependency or API key. Swapping the extraction step for API calls
  later would not affect the rest of the pipeline.
- **Own fetcher instead of WebFetch.** Claude Code's WebFetch summarizes pages with a smaller model,
  which can silently drop or alter table rows. Raw snapshots (with hashes) also make every finding
  reproducible.
- **Official sources only, honest client.** The user agent identifies as `sc-crawler-audit`.
  Pages that block automated clients (UpCloud and Vultr marketing pages at the time of writing)
  are reported as errors; **no bot-protection workarounds** (spoofed user agents, headless browsers).
- **Independence.** JSON feeds behind vendor pricing pages (AWS `b0.p.awsstatic.com`, the Alibaba
  price list) are official and *not* what our ingest reads, so they are independent checks. Sources
  our ingest uses (e.g. `prices.azure.com`, vendor APIs) are kept out, or marked `independent: false`.
- **Feeds are secondary for specs.** The AWS pricing feed has outdated specs (e.g. `i3.metal`
  64 vs 72 vCPUs, `c5.9xlarge` 10 vs 12 Gbps); the docs pages are authoritative.
- **Completeness is explicit.** `NOT_AT_VENDOR` only fires for pages marked `complete`, and only
  for SKUs matching `covers`, since most pages show a subset.

## Vendor notes

- **AWS**: specs from the docs pages (`docs.aws.amazon.com/ec2/latest/instancetypes/*.html`);
  prices from the pricing page feeds. The feeds leave out previous-generation types.
- **GCP**: pricing pages list per-machine-type prices (us-central1 by default) but no per-vCPU/GiB
  rates for predefined types (only custom types, which have a premium). Cloud SQL pricing has
  per-vCPU/GiB rates per edition/series, used for component checks.
- **Azure**: per-series pages are discovered from the docs `toc.json`, as many (e.g. the "d"
  variants) are not linked from overview pages. VM and PostgreSQL pricing pages are JS-only, so
  Azure prices are not checked.
- **Alibaba**: the price list (`g.alicdn.com/.../instancePrice.json`) is republished about weekly
  under an increasing version; the latest version is found by probing. `originalPrice` is the
  list price; `price` may include promotions. The list covers SKU/region pairs that may not be sold.
- **Hetzner**: product pages show prices including a primary IPv4 (billed separately, EUR 0.50/month)
  and for the cheapest locations; monthly prices are caps. "Currently unavailable" on the static
  pages is a placeholder of a client-side availability check.
- **OVHcloud**: database prices are per cluster (per-node price × nodes); `-eph` flavors are
  excluded by our ingest by design.
- **UpCloud, Vultr**: marketing/pricing pages block automated clients; only docs are covered.

## Extending

- **New page:** add it to `sources.yaml` with the right `kinds`, and `covers`/`complete` only
  if the page really lists every SKU of that pattern. Run `sc-audit fetch --vendor X --page ID`,
  then extract it with the skill.
- **New machine-readable source:** add a parser to `parsers.PARSERS` (and to `URL_RESOLVERS` if
  the URL changes over time), set `parser:` on the page, and add parser tests.
- **New vendor:** add a block to `sources.yaml` and, if its SKU names have optional prefixes, an
  entry in `export.SKU_PREFIXES`.
- **New check:** add it to `Comparer` in `compare.py`, give it a finding type and severity, and add
  a test with a small in-memory `Ours` fixture (see `tests/test_audit.py`).
- After a change to the vendor ingest, `sc-audit seed-urls` lists newly cited vendor pages.

## Run outputs

`audit-out/` is git-ignored. A run directory holds:

- `pages/`: snapshots of the vendor pages (raw HTML/JSON, Markdown, `*.meta.json` with the final
  URL, HTTP status, sha256 and fetch time);
- `extracted/`: extraction files;
- `ours/`: from `export`;
- `findings.jsonl`, `findings.csv` and `report.md`, plus optional free-form `notes.md` (included in
  `report.md`).

Persistent verdicts are not stored here but in `triage.yaml`, so they survive runs.

## Archiving runs

The raw pages are the evidence behind every finding, but they do not belong in git: about 190 MB
per run (mostly HTML, which also changes on every fetch, so diffs are noise), and verbatim copies
of third-party vendor content should not be published in this public repo. Instead, archive each
run and keep it in private storage (S3 or Google Drive):

```sh
sc-audit archive --out audit-out/2026-10-31
# -> audit-out/2026-10-31.tar.xz           (~9 MB for a full run of all vendors)
#    audit-out/2026-10-31.manifest.json    (same manifest, for a quick look without unpacking)
```

The archive contains the whole run directory, plus:

- `manifest.json`: sha256 and size of every file; the audited dump (`published_at`,
  `published_by`, `sc_crawler_version`); the tool version, git commit and whether the working tree
  was dirty; counts of pages, extractions and findings;
- `config/sources.yaml` and `config/triage.yaml` as used for the run.

`archive` re-reads the archive and verifies all checksums before returning.

**Upload:** keep the archive name, with one folder for all runs:

```sh
# S3
aws s3 cp audit-out/2026-10-31.tar.xz audit-out/2026-10-31.manifest.json \
    s3://<private-bucket>/audit-runs/
# Google Drive (via rclone, with a configured "gdrive" remote)
rclone copy audit-out/2026-10-31.tar.xz gdrive:audit-runs/
rclone copy audit-out/2026-10-31.manifest.json gdrive:audit-runs/
```

**Restore:** download, then `sc-audit verify-archive 2026-10-31.tar.xz` and
`tar -xJf 2026-10-31.tar.xz -C audit-out/`. `sc-audit compare --out audit-out/2026-10-31` works
again on the restored run, given the same data dump.

Reference archived evidence from triage entries with `evidence: audit-runs/2026-10-31.tar.xz`
(relative to the storage root), especially for `confirmed` findings and disputed values.
