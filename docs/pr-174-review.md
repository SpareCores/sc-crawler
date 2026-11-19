# PR #174 review: store non-GPU accelerators (`NPU`, `FPGA`, `VPU`)

- **PR:** https://github.com/SpareCores/sc-crawler/pull/174 (`NeonWest`, 13 commits, 14 files, +425/-49)
- **Reviewed:** head `9838aeb` against base `daef296`
- **Data:** cached vendor API responses from the repo root (Azure 2026-04-29, Alibaba 05-27, AWS 08-13) and `sc-data-all.db` (2026-10-21, which predates this PR). No fresh pull was run.

## Verdict: approve after two small fixes

The design is sound, and the mappings gave the right type for every accelerator in the cached AWS and Alibaba responses and for all three Azure NP sizes. The migration works on PostgreSQL in the normal paths. Before merge:

1. `dl1.24xlarge` probably stays `GPU`, although the changelog says Gaudi moves to `NPU`.
2. Trainium2 memory goes in about 5x too high, and the PR's own comment acknowledges the discrepancy.

Rollout order (D1) also matters more than anything in the code: published data with the new values may break a client on the current release.

## Must fix

### 1. `dl1` (Habana Gaudi) likely never becomes `NPU`

The Gaudi check at `vendors/_aws.py:643` only runs on instance types returned by `DescribeInstanceTypes`. `dl1` looks like it no longer is:

- It is missing from the cached `aws_servers.json`.
- Its on-demand prices were last seen on 2026-07-07, and only its spot prices are recent.
- It is ACTIVE with type `GPU` in the local DB, which fits the spot-only path.

For such rows, `_reconcile_server_status` (`vendors/_aws.py:365-370`) doesn't help:

| Stored type | Result after `_reconcile_server_status` (simulated) |
|---|---|
| `GPU` (existing DB) | stays `GPU` |
| `None` | set to `GPU` |

**Fix:** handle it in the reconcile loop, so both cases are covered, and add a test:

```python
if server.accelerator_family == "Gaudi":
    server.accelerator_type = AcceleratorType.NPU
```

**To confirm:** I made no live AWS calls. `aws ec2 describe-instance-types --instance-types dl1.24xlarge --region us-east-1` settles it, though an empty result covers that region only. If the API still returns `dl1`, the existing code is enough.

### 2. Trainium2 memory is stored about 5x too high

The comment at `vendors/_aws.py:601-604` notes the API/docs mismatch, but the code stores the API value anyway. These rows had 0 memory before, so this PR introduces the wrong number.

| Type | Stored by this PR | [AWS product page](https://aws.amazon.com/ec2/instance-types/trn2/) |
|---|---|---|
| `trn2.48xlarge` | 16 × 512 GiB, 8 TiB total | 16 chips, 1.5 TB total |
| `trn2.3xlarge` | 1 × 512 GiB | not checked |

Anything that sorts or filters on accelerator memory will overrate these servers.

**Fix:** override the memory for `Trainium2` (96 GiB per device, per the PR's comment), or store 0 as "unknown". `trn2u.48xlarge` has the same specs on the AWS page, so it needs the same treatment if the API returns it. It isn't in the cached response.

## Decisions for you

### D1. What order should the rollout happen in?

The latest release, 0.10.2 on PyPI, only knows `GPU` and `TPU`. The PR protects the inspector rules against this, and the `inspector-rules-on-release` job passes, but that covers the rules only.

A SQLAlchemy model using the old enum fails on any row with a new value. I reproduced this with a minimal two-value enum on SQLite: filtered reads of `GPU` rows work, and a full read raises `LookupError: 'NPU' is not among the defined enum values`. I didn't look at sc-keeper's code, so check how it reads these rows.

Three consumer-visible changes come with this:

- **`TPU` filters:** the 18 GCP TPU rows move to `NPU` on the next crawl, so a filter on `TPU` stops matching them. The changelog does list this as breaking.
- **Leftover `TPU` rows:** any machine type the API stops returning keeps `TPU`, so consumers need to accept both.
- **`accelerator_count > 0`:** inf, trn, f2, vt1 and dl2q servers go from 0 to a positive count. Nothing in this repo treats that as "has GPUs", but the API or UI might.

**Recommendation:** bump `__version__` (still 0.10.2, while the migration is named `v0_10_3`), release, update sc-keeper, and only then publish crawled data with the new values.

### D2. Do you keep `server` and `server_scd` in the same database?

If so, the downgrade fails. This is the open CodeRabbit finding, and I reproduced it on PostgreSQL 18:

```
DependentObjectsStillExist: cannot drop type acceleratortype_old
DETAIL: column accelerator_type of table server_scd depends on type
```

It fails with or without `--scd`, and rolls back cleanly. In that setup `upgrade --scd` after a plain `upgrade` is also a no-op, because they share one version table, so the `server_scd` comment stays stale. `b1c2d3e4f5a6` has the same downgrade shape (read, not run).

**Recommendation:** if the tables always live in separate databases, accept it. If not, retype whichever of the two tables exist.

### D3. Should Azure `Standard_PB6s` count as an FPGA too?

It is ACTIVE in the local DB with `accelerator_count` 0. The Azure API reports no `GPUs` capability for it, so nothing flags it. Third-party listings call it an FPGA series, but the Arria 10 model only comes from [a forum post](https://community.altera.com/discussions/quartus-prime/need-exact-link-for-fpga-installation-in-azure-vm/292069/replies/292070), and I found no Microsoft documentation.

**Recommendation:** leave it out of this PR unless you can confirm the hardware, and track it separately.

## Smaller issues

| # | Where | Issue | Suggestion |
|---|---|---|---|
| 1 | `CHANGELOG.md:12-14` | Promises `f1` as `FPGA`, but all 3 `f1` rows are INACTIVE with count 0 and aren't in the cached API response, so they likely won't change. | Reword, or backfill them |
| 2 | `_alicloud.py:476-479` | Descriptions say "VRAM" for FPGA, VPU and NPU cards. Rows with no reported memory read `4xALINPU 800 0 GiB VRAM` (29 Alibaba rows have 0 memory). | Say "memory", and omit it when 0 |
| 3 | `_alicloud.py:463-471` | The GPU-or-NPU call for `PPU 810` and `A910*` has no source, and I couldn't confirm it. `VG1000` defaulting to GPU is also unsourced. | Add a source, or flag as best effort |
| 4 | `c7d8e9f0a1b2:66-73` | Downgrade sets all new values to NULL, including GCP TPUs that could return to `TPU`. | Restore GCP rows to `TPU` |
| 5 | `c7d8e9f0a1b2:47` | The comment says other dialects store a plain string, but `schemas create --dialect mysql` emits a native `ENUM`, so an existing MySQL DB wouldn't accept the new values. `b1c2d3e4f5a6` makes the same skip. | Fix the comment; handle MySQL only if it is actually used |
| 6 | Open PRs #157, #170 | Their migrations also branch from `37c49fd74cce`, so whichever merges later creates a second head. `pull` upgrades to `heads`, so this wouldn't fail loudly. | Rebase after merge |
| 7 | `_azure.py:820`, `_alicloud.py` | `accelerator_manufacturer` is NULL for the NP series (the comment says Xilinx) and for Alibaba's non-GPU cards. | Fill it in where known |
| 8 | `tests/test_aws.py` | No fixture has both `NeuronInfo` and `InferenceAcceleratorInfo`, which real `inf1` and `inf2` types do. | Add a case |
| 9 | PR description | The checklist is mostly unticked, including the migration tests and `sc-crawler pull`. | Tick or run them |

## What checks out

**AWS**
- All five accelerator info shapes match the botocore EC2 model, including `Manufacturer` being absent on Neuron devices.
- All 20 non-GPU types in the cached response get the right type, count and manufacturer: `f2`, `dl2q`, `inf1`, `inf2`, `trn1`, `trn1n`, `trn2`, `vt1`. None has a zero count or zero memory.
- The 8 `inf1` and `inf2` types carry two info keys. `NeuronInfo` wins and nothing is double counted.
- The GPU families stay `GPU`.

**Alibaba**
- All 9 mapping keys match real `GPUSpec` values in the 1916 cached types, and everything else falls back to `GPU`.
- Placeholder values (`0`, `NA`, `NULL`) give no type.
- The GiB fix is right. The old description really did read `65536 GiB VRAM`.

**Azure and GCP**
- NP counts of 1, 2 and 4 match the `GPUs` capability exactly, and no other SKU reporting `GPUs` is missed by the parser.
- The GCP change is a straight `TPU` to `NPU` swap. `accelerator_family` stays `TPU`, and the price logic keys off the TPU version rather than the type.

**Shared code**
- `_standardize_gpu_model`, `_standardize_gpu_family` and `_standardize_gpu_count` leave every new model name intact. Only `Gaudi HL-205` changes, to `HL-205`, as it did before.
- The inspector rule is correct and is tested for every non-GPU type. `None` is deliberately still allowed.

**Migration, on a throwaway PostgreSQL 18**

| Scenario | Result |
|---|---|
| Upgrade, downgrade, upgrade again | Pass. Existing `GPU` and `TPU` rows survive, comments update. |
| Re-run after `stamp` | Pass (`IF NOT EXISTS`) |
| SCD-only DB, up and down with `--scd` | Pass |
| Empty DB to head, in one transaction | Pass |
| New values through the `Server` model | Read without error |

**Tests and earlier reviews**
- All 405 tests pass locally. `build`, `docs` and `inspector-rules-on-release` pass in CI.
- CodeRabbit's two AWS findings (missing device lists, missing memory keys) are fixed. It then hit its rate limit, so it has not reviewed the final head.

## Differences not caused by this PR

- **`g3`, `p2`, `p3`:** 10 INACTIVE AWS rows have a count above 0 and NULL type. The spot-only fallback only fills ACTIVE rows, and a test asserts that.
- **`schemas upgrade --scd` on an empty DB:** fails in an older part of the migration chain, so I built the SCD test tables by hand from the migrated `server` table.

## Limits of this review

- No live vendor API calls and no `sc-crawler pull`. AWS, Alibaba and Azure results rest on the cached responses above, which may be months old. GCP is covered by unit tests only.
- sc-keeper and the UI were not inspected, so D1 is about risk, not an observed failure.
- `ruff` isn't installed in the local `.venv`, so lint wasn't run locally.
- Vendor doc checks covered only the Trainium2 page. The PB6s and Alibaba searches turned up mostly third-party listings.
