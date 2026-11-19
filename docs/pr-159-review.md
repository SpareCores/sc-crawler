# PR #159 review: family/series classification and `compatible_storage_ids`

- **PR:** https://github.com/SpareCores/sc-crawler/pull/159 (`NeonWest`, 60 commits, 18 files, +6198/-3429)
- **Reviewed:** head `5137b32` against base `616a1a0`
- **Data:** `sc-data-all.db` (fresh pull from this branch) vs `sc-data-all-prod.db` (prod, published 2026-11-05, v0.10.2)

## Verdict: request changes

The core work is solid. `compatible_storage_ids` has no broken references, `series` carries over cleanly, and prices did not regress. Two things should be settled before merge:

1. 9 ACTIVE GCP Cloud SQL tiers end up with no family, series or storage.
2. 17 UpCloud High CPU / High Memory plans are now labelled General Purpose.

You also need to decide whether `family` should be comparable across vendors (D1). That decision affects how much of the labelling needs rework.

## Must fix

### 1. GCP C4D tiers lost all classification

`perf-optimized-C4D` is missing from both `_PG_TIER_FAMILY_SERIES` and `_PG_TIER_STORAGE_IDS` (`vendors/_gcp.py:2451`, `:2471`). The regex fallback can't match it either.

| Rows | Prod `family` | Fresh `family` / `series` / `compatible_storage_ids` | Fresh status |
|---|---|---|---|
| 9 (`db-perf-optimized-C4D-2` … `-192`) | `perf-optimized-C4D` | all NULL | ACTIVE (INACTIVE in prod) |

**Fix:** add C4D to both tables. `("General Purpose", "C4D")` follows from the PR's own Compute Engine table. `["cloudsql-hyperdisk"]` is likely, because the PR's tables give Compute Engine `c4d` no Persistent Disk support. However, the [Cloud SQL machine series page](https://docs.cloud.google.com/sql/docs/postgres/machine-series-overview) doesn't mention C4D, so confirm the storage type before hardcoding it.

**Why INACTIVE in prod but ACTIVE here:** this PR doesn't change it. The status of a Cloud SQL tier is its linked server's status, or ACTIVE if no server matches (`vendors/_gcp.py:2689`). A tier like `db-perf-optimized-C4D-16` never matches a server (those are `c4d-standard-*`), so every pull sets it ACTIVE. In prod the rows were INACTIVE with `observed_at` 08:36:11 and the price rows 08:36:20, which is what the merge step writes for rows missing from a crawl (`cli.py:531-537`). So the 08:36 run's Cloud SQL tier list most likely had no C4D tiers, and the fresh pull at 10:53 did. Whether that is the API changing or a stale cache of `_pg_sqladmin_metadata` (`@cachier`) I can't tell from the DBs. The C4D family is therefore likely to flap in prod, so the lookup fix matters.

### 2. UpCloud High CPU / High Memory became General Purpose

The PR replaced the name-prefix mapping with the undocumented `family` field from the plans API (`vendors/_upcloud.py:528`). That field returns `general_purpose` for the old plans:

| Plans | Rows | Prod | Fresh |
|---|---|---|---|
| `HICPU-*` | 8 RETIRED | High CPU | General Purpose |
| `HIMEM-*` | 9 RETIRED | High Memory | General Purpose |

- **Lost information:** `HIMEM-24xCPU-512GB` as General Purpose is a wrong label, and the `description` text changed with it (e.g. `High CPU (16 vCPUs…)` is now `General Purpose (16 vCPUs…)`).
- **Empty series:** `series` is NULL on 114 of 152 UpCloud rows, including every one of these plans, so nothing else preserves the distinction.

**Fix:** keep the name-prefix mapping as an override for these two prefixes, or at least store `HICPU` / `HIMEM` in `series`.

## Decisions for you

### D1. Should `family` be comparable across vendors?

Today each vendor keeps its own wording. That matches your earlier "use the vendor's API" comment, but a cross-vendor filter on `family` won't work:

| Concept | Values in the fresh DB |
|---|---|
| General purpose | `General Purpose`, `General-purpose` (Alibaba), `Regular Purpose` (Hetzner) |
| GPU | `Accelerated Computing`, `GPU Accelerated`, `GPU Machines`, `Compute-optimized with GPU`, `Cloud GPU`, `GPU`, `Dedicated Metal GPU` |
| HPC | `High-Performance Computing`, `High Performance Compute` |

**Recommendation:** at minimum normalize spelling and case (`General-purpose` → `General Purpose`, one HPC spelling). If the UI needs a cross-vendor facet, add a canonical mapping rather than overloading `family`.

### D2. What does `database.family` mean?

The schema says "Hardware family or class classification", but vendors fill it with different things:

| Vendor | Meaning | Example |
|---|---|---|
| AWS, GCP | Workload class | `Memory Optimized` |
| Azure | Pricing tier | `Burstable`, `General Purpose` |
| OVH, Vultr | Service tier, not hardware | `Production`, `Business` |
| UpCloud | Plan group | `Legacy`, `High Memory` |

For example, OVH's `Production` database on `b3` links to a server with family `General Purpose`.

**Recommendation:** either accept this and change the field description, or move service tiers elsewhere.

### D3. Should database and server `series` match?

They currently don't join:

| Vendor | Database series | Server series | Exact matches |
|---|---|---|---|
| GCP | `N1`, `N2`, `C4`, `C4A` | `n1`, `n2`, `c4`, `c4a` | 0 of 6 |
| GCP | `Shared Core`, `Memory-optimized-N2` | no equivalent | |
| Azure | `Dsv3`, `Ddsv5`, `Bs` | `DSv3`, `DDSv5`, `BS` | 2 of 15 |
| Azure | `Dadsv6`, `Eadsv6` | `Dadv6`, `Eadv6` (differ beyond case) | |
| AWS | | | 41 of 42 (`x2g` has no EC2 type) |
| Vultr | | | all 5 |

**Recommendation:** make them match where a database runs on a known server type. For GCP, drop `.upper()` at `vendors/_gcp.py:2521`.

### D4. How far should Alibaba coverage go?

| Field | Missing | Cause |
|---|---|---|
| `family` | 61 ACTIVE (16 old series, e.g. `ecs.c1`, `ecs.n1`), 139 INACTIVE | No `InstanceCategory` from the API |
| `compatible_storage_ids` | 17 ACTIVE, all 968 INACTIVE | Not listed in `DescribeZones` |

NULL is honest here, so this could ship as is. The bigger question is accuracy. The code itself notes that per-instance accuracy is "not confirmed", and that `sn2ne` contradicts the docs ("not resolved"). PL0–PL3 are also assumed for every ESSD type. `DescribeAvailableResource` with `DestinationResource=DataDisk` may give a true per-type answer, but I haven't tested it and it could be costly in API calls.

## Smaller issues

| # | Where | Issue | Suggestion |
|---|---|---|---|
| 1 | `_alicloud.py:879-884` | A failed region is logged and returns `{}`, and cachier stores that until the TTL expires. Types offered only in that region silently lose categories or become NULL. | Don't cache failures; report through Sentry |
| 2 | `_aws.py:664-676` | If the Pricing API fails, the mapping is `{}` for the run. Only the 12 fallback series keep a family, and the rest are written as NULL. | Fail the server inventory, or keep the previous values |
| 3 | `_vultr.py:345` | Non-GPU bare metal has NULL `series` (14 rows), while OVH uses `bm`. | Use `vbm` |
| 4 | `_vultr.py:345`, `_upcloud.py:546` | GPU model used as series, so `a100` spans 3 Vultr families and series doesn't nest under family. | Accept and document, or use the plan line |
| 5 | `_vultr.py:1028` | 14 `vcg-*` GPU plans claim block storage, including those labelled Dedicated Metal GPU. The Vultr page I checked only covers Cloud Compute, and the code comment has no source. | Verify |
| 6 | Alibaba data | 31 `ecs.poc-test.*` INACTIVE rows spread over 6 families (already in prod). | Filter out test types |
| 7 | `_gcp.py:245` | The PR's `family` for accelerators is `GPU Machines` / `TPU Machines`, while your request named Google's categories ("General purpose", "Storage optimized"). | Confirm you're happy with the split |
| 8 | `table_bases.py:644`, `:646`, `:953` | Field docs are stale (`M5g (AWS)`, `TODO populate`). `NULL` = unknown vs `[]` = none isn't documented, nor that compatibility is vendor-wide rather than per region. | Update the field descriptions |
| 9 | `CHANGELOG.md`, `docs/add_vendor.md` | Neither is touched, and the PR checklist is mostly unticked. | Add a changelog entry; the `family` meaning change is breaking for consumers |
| 10 | PR description | Doesn't call out the extra behavior changes listed below. | Mention them |

**Extra behavior changes beyond the stated scope:**

- **UpCloud `ipv4`:** changes from 1 to 0 on 42 Cloud Native plans. It looks like a genuine bug fix, because the old check compared against `CLOUDNATIVE` after that value had been remapped, so it never matched. It deserves a changelog line.
- **Azure disk meters:** the hardcoded table is now derived from the API. No data changed: all 7 storage rows are identical and none of the 361 matching prices differ.
- **Azure retirement dates:** these now come from the API first. No Azure server status changed.
- **Tests:** `test_databases.py` was split into per-vendor files.

## What checks out

**`compatible_storage_ids`**
- No broken references and no duplicates in `server` or `database`. Every storage is referenced except Azure's `BackupStorageLRS`, which is correctly left out.
- Coverage went from 0% in prod to every fresh row except the Alibaba NULLs above, GCP C4D, and 35 retired AWS RDS classes (intentional).
- Database compatibility agrees with `storage_extra_max`: Vultr is `[]` with 0, and every other populated row has a non-empty list with a positive maximum.
- Azure's non-premium group is what you'd expect (`Dv3`, `Ev5`, `Av2` and similar non-`s` sizes).
- GCP's disk tables matched Google's docs on what I sampled: Hyperdisk support, Extreme minimum vCPUs and the bare-metal Throughput exclusion. This was a sample via page summaries, not a cell-by-cell check. The N2D Throughput row, which looked suspicious at first, is correct.
- Azure's Burstable exclusion for Premium SSD v2 matches Microsoft's docs. The other Azure database storage lists come from the API and weren't checked independently.

**Family and series**
- `series` equals the old `family` for all AWS, GCP and Alibaba rows, and for 1475 of 1481 Azure rows. The other 6 only had whitespace trimmed.
- AWS has no NULL family. Azure has one (`Standard_PB6s`), which is intentional.
- Azure's D11–D15 sizes correctly split out as Memory Optimized.
- OVH gained a family for `h200`, which was NULL in prod.
- AWS RDS labels improved: `m8gd` is no longer "Memory optimized". The one to glance at is retired `m2`, now General Purpose, which follows the EC2 Pricing API.

**Earlier review threads**
- Your AWS request is done: `instanceFamilyCategory` is the main source, `_get_server_products` is cached, and a small fallback remains. The code says RDS products have no such attribute, which I couldn't verify without AWS credentials.
- Your GCP request to fill `family` is done.
- All 11 CodeRabbit inline findings are addressed in the current code. CodeRabbit itself is paused and last reviewed `7aadfa8`, not the current head.

**Tests and prices**
- All 529 tests pass locally. All 52 tests from `test_databases.py` still exist, and the moved Alibaba GPU test is in `test_alicloud.py`.
- Azure's database price lookup still works after the `family` change: all 118 ACTIVE databases have prices.
- Missing test: nothing checks that storage ids exist in the storage tables, or fails on unknown tiers such as C4D. Unknown tiers only log a warning, so C4D passed unnoticed.

## Differences not caused by this PR

These appear in the data comparison but the PR doesn't touch the relevant code. They may deserve separate tickets:

- **`db-f1-micro`, `db-g1-small`:** ACTIVE with no prices in the fresh pull. Their prod price rows are already INACTIVE, so this looks upstream.
- **Azure CPU fields:** 49 rows, mostly confidential sizes (`DC*`, `EC*`), have NULL `cpu_*` values in the fresh DB but values in prod. I didn't find the cause.
- **Lower row counts in the fresh DB:** expected, because it has no history. Prod-only rows are INACTIVE and get their status flipped on merge.

## Limits of this review

- No live vendor API calls were made. API-derived values were checked for consistency, not against the source.
- Vendor doc checks covered GCP Hyperdisk and Cloud SQL, Azure PostgreSQL Premium SSD v2, and Vultr block storage. Alibaba, Hetzner, OVH, UpCloud and AWS storage claims were not checked against docs.
