# PR #157 review: handle `ARCHIVED` records

- **PR:** https://github.com/SpareCores/sc-crawler/pull/157 (`superseded-regions`, 16 files, +1957/-61)
- **Reviewed:** head `f140ecd` against `main` at `170f03f`
- **How:** read the full diff, ran `tests/test_archive_rules.py`, `test_schemas.py` and `test_insert.py` (pass, Python 3.14, SQLite), and probed the models directly. Nothing was run on PostgreSQL and no `pull` was run.

## Verdict: good to merge after a PostgreSQL run

No blocking bug found. The design holds together: one matching definition (`get_key_filters`) drives both the SQL in `pull` and the Python matching in `sync`, every code path that resets statuses now skips `ARCHIVED`, and the tests cover the paths I tried to break. The findings below are edge cases and small robustness gaps.

The one open item is PostgreSQL: the migration and the `JSONB` switch in `HashableJSON` are untested there (also unticked in the PR checklist).

## Findings

### 1. Enum columns in a rule only work when given by value (medium, latent)

No current rule uses an enum column, so nothing is wrong today. A future rule on e.g. `server_price.allocation` behaves differently depending on spelling:

| `match` value | `check()` | `pull` (SQL) | `sync` (Python) |
|---|---|---|---|
| `"spot"` (value) | passes | archives | archives |
| `"SPOT"` (name, as stored in the DB) | passes | archives | **does not match, row becomes `INACTIVE`** |

SQLAlchemy accepts both spellings in the bind, while `matches_rule` compares with `==`, where only the value equals the `str` enum member. Whoever copies the value from the database gets the second row.

**Fix:** in `ArchiveRule.check`, reject `match`/`successor` values of enum columns that are not a member value (`archived_by` already has the column-type lookup to reuse), and say so in the `archive_rules.py` docstring.

### 2. Rules are `INACTIVE` in the database for the whole `pull` run (low)

`pull` sets all `archive_rule` rows to `INACTIVE` up front (`cli.py:931-940`) and restores them only in `ArchiveRule.apply` as the very last step (`cli.py:1029`), with a commit after each vendor in between. If the run dies after the first vendor commit, the rules stay `INACTIVE` until the next successful `pull`, and `archived-by` reports live rules as removed. The archived data rows themselves are not affected.

**Fix:** move the reset into `apply`, next to the insert, so both land in the same commit.

### 3. `copy --exclude-status` misses references without a foreign key (low)

The docstring says rows referencing a left out row are left out too, but only foreign keys are followed (`cli.py:398-407`). `benchmark_score` points to its server or database through `resource_type`/`resource_id`, so `--exclude-status inactive` keeps the scores of excluded servers. With `archived` it works in practice, as those scores are archived themselves.

**Fix:** either narrow the docstring to foreign keys, or reuse `get_key_filters` for the lookup.

### 4. `sync` warns about unmatched rules on databases that never had the old records (low)

`find_unmatched` reports every rule whose `match` is in neither database. Syncing two databases built after v0.10.1 logs 12 Hetzner warnings and the benchmark one on every run. Production is fine, as the target has the old records. Consider logging these at `DEBUG`, or warning only on a missing `successor`.

### Nits

- `get_parent_tables` returns the cached `set` itself, so a caller mutating it corrupts the cache. Return a `frozenset`.
- `ArchiveRuleFields._sort_keys` writes into the caller's dict, and `ArchiveRule.__init__` repeats the same sorting. Fine as is, but one copy (`{**values}`) would avoid the side effect.
- `CHANGELOG.md` is dated November 13; update on release.

## Checked and fine

- `HashableJSON` → `JSONB` on PostgreSQL: `benchmark_score.config` was already created as `JSONB` by the v0.9.0 migration, so no column needs retyping.
- Migration: `_STATUS_TABLES` covers all 19 tables with a `status` column; the downgrade follows the same enum-recreate pattern as v0.9.2.
- `copy`: `tables` is ordered so that referenced tables always come first, so `left_out[...]` cannot raise `KeyError`.
- Parent/child matching: every parent's primary key columns exist on its children, apart from `benchmark_score` → `server`/`database`, which the override maps.
- `sync` status lookup: keys from the column `select` match the keys from `hash` for enum and dict primary keys.
- All other status resets (`set_table_rows_inactive`/`_active`, static models in `pull`, workload profile scores) skip `ARCHIVED`.
- `ArchiveRule.check()` returns no problem for the current rules.

## Changes made with this review

Uncommitted, in `src/sc_crawler/table_bases.py` and `src/sc_crawler/table_fields.py`; lint, the related tests and doctests pass.

- `get_parent_tables`: docstring describes the parent relation in general, with a doctest, and no longer mentions archiving.
- `ArchiveRuleFields.match`: the comment states the reason itself instead of pointing to `BenchmarkScoreFields.config`.
- `Status`: the value docstrings say only what each status means; how and where each is set moved to the class docstring.

Finding 1 is fixed: `ArchiveRule.check` reports enum columns not given by a member value (with tests), and the `archive_rules.py` docstring says to use the value. Findings 2-4 and the nits are not fixed.
