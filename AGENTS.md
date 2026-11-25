# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## What this is

`sparecores-crawler` (import name `sc_crawler`, CLI `sc-crawler`) pulls cloud compute data (regions, zones, servers, storages, managed databases, and their prices) from vendor APIs, enriches servers with hardware inspection and benchmark data, and writes it into a standardized SQLModel/SQLAlchemy schema (SQLite or PostgreSQL). It is the data layer of Spare Cores Navigator. The `sc-keeper` (API) and `sc-runner` (provisioning) repos depend on it, and `sc-www` uses its schema through the `sc-keeper` OpenAPI spec. Python >= 3.11; CI tests 3.11 (production) and 3.14.

## Commands

```sh
pip install -e ".[all]"          # dev install: testing + all vendor SDKs + sentry
pytest                            # all tests (tests/ only; audit/ is excluded in pyproject)
pytest tests/test_hcloud.py::test_hcloud_location_status   # single test
tox                               # what CI runs: pytest --doctest-modules over src + tests
tox -e lint                       # ruff check, import ordering (ruff check --select I), ruff format --check
ruff check --select I --fix . && ruff format .   # fix lint/format locally
python scripts/gen_md_docs.py     # docs build check (needs .[mkdocs]); fails on unresolved refs / undocumented enum values
```

Doctests run over `src/`, so docstring examples must stay correct. Alembic migration files are excluded from doctests.

Main CLI flows:

```sh
sc-crawler pull --connection-string sqlite:///sc-data-all.db --include-vendor hcloud --cache   # crawl vendor APIs
sc-crawler sync --source sqlite:///new.db --target sqlite:///old.db [--scd]    # diff/upsert into another DB (SCD history)
sc-crawler schemas create|upgrade|downgrade|stamp|autogenerate|current ...      # DDL and Alembic migrations (--scd/--no-scd, --sql prints instead of applying)
sc-crawler dump --connection-string sqlite:///sc-data-all.db --output-directory ./dump --dump-tables server   # one JSON per record, by vendor
sc-crawler copy / hash / archived-by
```

`pull --include-records servers` (repeatable, also `--exclude-records`) limits the crawl to some tables. On an empty DB, include the parent records too (e.g. `regions` and `zones` for `servers`). To check the effect of a crawler change, dump the old and new DBs and `diff -r` them, or diff against the JSON dumps in the `data/` folder of the [sc-data-dumps](https://github.com/SpareCores/sc-data-dumps) repo (`git pull` any local checkout first). `sqldiff` output is noisy because of `observed_at`, so filter it or `ATTACH` both DBs and query them.

`--cache` caches vendor API calls on disk via `cachier` (`~/.cachier`); it is off by default. Set `SC_CRAWLER_INSPECTOR_DATA_PATH` / `SC_CRAWLER_DESCRIPTIONS_DATA_PATH` to reuse downloaded copies of the `sc-inspector-data` and `sc-navigator-descriptions` GitHub repos between runs. Otherwise each process downloads them into a temp dir. Vendor credentials and IAM requirements are documented in `docs/index.md` ("Collect data"). Never write credentials to disk.

`mkdocs serve` breaks on the Alembic files: delete `src/sc_crawler/alembic` and `docs/reference/sc_crawler/alembic` temporarily, then restore them with git.

## Architecture

**Schema layering** (`table_fields.py` → `table_bases.py` → `tables.py` / `tables_scd.py`):

- `table_fields.py`: enums (`Status`, `Allocation`, `PriceUnit`, ...) and Pydantic JSON column types (`Disk`, `Gpu`, `PriceTier`, ...).
- `table_bases.py`: `ScModel` and the `*Fields`/`*Base` mixins. The `ScMetaModel` metaclass turns field descriptions into SQL column comments and docstring `Attributes`, sets the Alembic naming convention, and sets `__validator__` to the parent `*Base` Pydantic model, which `insert.py` uses for validation. **Field descriptions matter**: they become DB comments and published docs.
- `tables.py`: the `table=True` models plus `Vendor`, which also holds the crawler orchestration. `tables_scd.py`: SCD Type 2 twins (`*Scd`, `_scd` table suffix) used by `sync --scd`.
- Every table has `MetaColumns` (`status`, `observed_at`).

**Vendor plugins** (`vendors/`): `vendors/vendors.py` defines one `Vendor(...)` instance per provider (aws, gcp, azure, hcloud, upcloud, ovh, alicloud, oci, vultr). `Vendor._get_methods()` lazily imports `vendors/_<vendor_id>.py` and requires all 14 `inventory_*` functions (regions, zones, servers, server prices, spot prices, storages, databases, traffic/IPv4 prices, ...). Each takes the `Vendor` and returns a list of dicts. `Vendor.inventory_*` marks existing rows of that table INACTIVE (except `ARCHIVED` rows and `PLANNED_FOR_RETIREMENT`/`RETIRED` servers and databases, which keep their status), then calls `insert.insert_items`, which validates, dedupes by PK, and bulk-inserts (SQLite) or `session.merge`s (other DBs). Prices are rounded to 4 decimals. `Vendor.inventory_servers` additionally enriches each server from sc-inspector-data (`inspector.py` parses lscpu/lstopo/dmidecode/benchmark outputs), loads `BenchmarkScore`s, and ingests `ServerDescription`s. Shared helpers for vendor modules are in `vendor_helpers.py`, e.g. `parallel_fetch_servers`, the disk speed helpers and the retirement date helpers. Static reference data (countries/continents, compliance frameworks, benchmark definitions) is in `lookup.py`.

**Adding or changing a vendor**: follow `docs/add_vendor.md`. It has the full checklist (register in `vendors/__init__.py`, optional dependency extra in `pyproject.toml`, `country_continent_mapping`, `audit/sources.yaml`, inspector `_boot_from_attached_network_drive`, ...) and a template module. Non-`inventory_*` functions in vendor modules must be `_`-prefixed. Vendor tests mock API responses.

**Status rules** (from `docs/add_vendor.md`): set `status` on every Server/Database from explicit vendor lifecycle signals only. Do not infer retirement from names like "previous generation". When several signals exist, pick the best (`ACTIVE` > `PLANNED_FOR_RETIREMENT` > `INACTIVE` > `RETIRED`; see `Status.best`). Set `retirement_date` on `PLANNED_FOR_RETIREMENT`/`RETIRED` rows when the vendor publishes one (end of support if published, else end of sale), preferably from the API; docs-only dates go in a `_<VENDOR>_RETIREMENT_RULES` tuple of `(regex, date)` pairs with source URLs, matched by `retirement_date_from_rules`. If the date is the only lifecycle signal, derive `status` with `status_from_retirement_date`. **Never set `ARCHIVED` in vendor code.** Archiving happens only through `archive_rules.py`, which `pull` and `sync` apply on every run. When record ids change, add an old → new `ArchiveRule` per pair, and never remove a rule that has archived records.

**Inspector rules** (`inspector_rules.py`): `sc-keeper` overlays this file from `main` onto the PyPI release with the same version. A CI job checks that it stays compatible with the released package, so it must not depend on unreleased code elsewhere in the package.

**Benchmark scoring**: `workload_profiles.py` defines weighted workload profiles. `workload_profile_scores.py` computes compound scores (geometric mean vs. median baselines).

## Schema changes and migrations

Migrations live in `src/sc_crawler/alembic/versions/` (named `v<x_y_z>_<message>`), driven by `sc-crawler schemas ...`. Every migration must handle both SCD and non-SCD tables and both SQLite (live, batch table recreation with `insert_after` positioning) and PostgreSQL (offline). Enums need dialect-specific handling. Follow the step-by-step procedure in `src/sc_crawler/alembic/README.md` instead of using raw autogenerate output. User-visible schema and data changes are described in `CHANGELOG.md`: the feature entry notes whether existing rows are backfilled by the migration or only by the next inventory refresh, and each release with a migration lists its DDL changes (tables and columns, including `_scd` tables) under a `Database migrations:` section. The version is in `src/sc_crawler/__init__.py`.

## Production and releases

Internal and sensitive information (e.g. the shell script that sets the environment variables for testing `sc-crawler pull`, or the production database and rollout runbooks) is in the `crawler` folder of the private `sc-docs` repo, for maintainers with access: start with the `README.md` there. Never copy its content into this public repo.

- The scheduled crawl runs from the GitHub Actions of the [sc-data-dumps](https://github.com/SpareCores/sc-data-dumps) repo, which install the crawler from the `main` branch of this repo, so **every merge to `main` goes to production on the next run**. Full runs crawl all vendors and records; more frequent spot runs update only the spot prices.
- The published SQLite dumps are available on the CDN (see `README.md`) and via the [sc-data](https://github.com/SpareCores/sc-data) repo (`sparecores-data` package). Use these to check real data. The CDN path follows the crawler's major.minor version, so a minor version bump starts a new path.
- Production uses the SCD tables in PostgreSQL, so call out new tables and primary key changes in the PR.
- Release: bump `__version__`, finalize the `CHANGELOG.md` section (`## vX.Y.Z (Month DD, YYYY)`), then push a `vX.Y.Z` tag (or create a GitHub release). `release.yml` publishes it to PyPI. Versioning: minor for backward-compatible features and new columns, patch for fixes, major for breaking changes or changes that need manual DB work.
- Major or minor releases (e.g. schema changes) need matching `sc-keeper` PRs and possibly `sc-www` PRs (frontend references column names).

## Vendor data audit (`audit/`)

`audit/` is a separate, unpublished project (`sc-audit` CLI, own `pyproject.toml` and tests: `pip install -e "audit[testing]"`, `cd audit && pytest`). It cross-checks the published SQLite dump against official vendor pages only. Outputs go to `audit-out/` (git-ignored). Use the `vendor-audit` skill (`.claude/skills/vendor-audit/`) for audits, and read `audit/README.md` before changing the tool or triaging findings.

## Code style

- Don't create helper functions that are called from only one place; write the logic inline at the call site.
- Skip defensive fallbacks and redundant casts:
  - Use direct attribute access on typed SDK models (`obj.field`), not `getattr(obj, "field", None)`.
  - On dicts, use `d.get(key, default)` instead of `d.get(key) or default`. The exception is a key that can be present with a `None` value (e.g. a `null` field in a vendor API response), where `or default` is still needed to get the default.
  - Only wrap values in `float()`, `int()` or `str()` when the type actually needs converting.
- When there is nothing meaningful to store, use `None` or leave the field out instead of storing `{}` or `[]`.
- Keep comments and log messages short, simple and precise. Leave out comments that only restate what the code already shows.
- A URL in a comment must be valid, point to the actual source of the information, and relate to the code it annotates.

## Repo hygiene

The repo root may contain many git-ignored scratch files (vendor API JSON dumps, `*.log`, `*.sql`, `sc-data-all.db`, ...). They are local artifacts, not source of truth.
