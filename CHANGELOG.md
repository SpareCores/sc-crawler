## v0.12.x (DEVELOPMENT)

Fixes:

- Hashing of date columns (e.g. `retirement_date`) (#197)

## v0.12.0 (November 21, 2026)

New features:

- `Server.retirement_date` and `Database.retirement_date`: the retirement date
  announced by the vendor for `PLANNED_FOR_RETIREMENT` and `RETIRED` records,
  i.e. the end of support (shutdown) if published, otherwise the end of sale.
  Empty when no date was announced or it is not known (#195)

Fixes:

- Servers and databases no longer returned by the vendor keep their
  `PLANNED_FOR_RETIREMENT` and `RETIRED` status, instead of becoming `INACTIVE`
  (#195)
- `gcp`: the deprecated `n1-megamem-96` and `n1-ultramem-40/80/160` machine
  types are archived with archive rules, as GCP renamed them to
  `m1-megamem-96` and `m1-ultramem-40/80/160` (the old names are aliases). The
  deprecated `z3-highmem-88` and `z3-highmem-176` are archived as well, as
  their API replacements (`z3-highmem-88-highlssd` and
  `z3-highmem-176-standardlssd`) have the same specs and prices (#195)
- `oci`: the previous generation `Standard2`, `Standard.E2` (except for the
  Always Free `VM.Standard.E2.1.Micro`) and `Standard.E3` shapes are
  `PLANNED_FOR_RETIREMENT` instead of `ACTIVE`, as these are past their end of
  orderability date, but can still be ordered (#195)
- `ovh`: PostgreSQL SKUs with an end of sale date of their plan or flavor are
  `PLANNED_FOR_RETIREMENT` (or `RETIRED` after that date) instead of `ACTIVE`
  (#195)

Database migrations:

- Add the `retirement_date` column to the `server`, `server_scd`, `database`
  and `database_scd` tables (#195)

## v0.11.1 (November 20, 2026)

New vendors:

- Oracle Cloud Infrastructure (`oci`): regions, availability domains, servers
  (shapes) with on-demand and preemptible prices, block volumes, traffic and
  IPv4 prices. Flexible shapes are listed as a grid of OCPU and memory
  configurations, each stored as a separate server (e.g.
  `VM.Standard.E5.Flex.4-32`). Managed PostgreSQL (OCI Database with
  PostgreSQL) shapes are listed as databases with single-node, single-zone and
  multi-zone readable cluster prices, and the performance tiers of the database
  optimized storage as database storages (#180)

New features:

- `Server.storage_read_iops_max`, `storage_write_iops_max`,
  `storage_read_throughput_max` and `storage_write_throughput_max`: the
  vendor-published maximum performance of the bundled (local) disk(s),
  summed over the disks with a known speed, also of different types (a
  theoretical total; partial if only some disks have a known speed). Empty
  when the vendor does not publish it. Populated for `alicloud`, `aws`, `gcp`
  and `upcloud` from the vendor docs, for `azure` from the API (with docs for
  the NVMe disks of L-series and HPC sizes), and for `ovh` from the catalog
  (read IOPS only). Existing rows are not backfilled by the migration, only by
  the next inventory refresh (#182)
- `Disk` items of `Server.storages`: `read_iops_max`, `write_iops_max`,
  `read_throughput_max` and `write_throughput_max`, the same speeds per
  entry. Where the vendor only publishes server totals over identical disks
  (`aws`, most `alicloud` types), the totals are split evenly; `alicloud`
  i2/i2g use their documented per-disk figures. `storages` now lists one
  entry per drive also for the GCP Local SSD partitions and the Azure NVMe
  disks (e.g. 10 x 1,920 GB on `Standard_L80as_v3`, was one entry of the total
  size), and is now also filled for `alicloud` (one entry per local disk)
  and `upcloud` (the plan disk). Azure temp disk speed is the API's combined
  temp disk and host cache limit, left empty when above the NVMe speed of the
  same size (HBv3). `alicloud` i2/i2g server totals stay the instance
  limits (or empty where not published), so they do not equal the sum of the
  per-disk figures (#182)

Fixes:

- `upcloud`: plans on the `hdd` (Archive) storage tier have the `HDD` storage
  type (was `SSD`) (#182)
- `gcp`: C4D bare metal sizes (e.g. `c4d-standard-384-lssd-metal`) have
  3,000 GiB Local SSD disks (was 375 GiB), so their `storage_size` grows (#182)
- `aws`: Pricing API clients use adaptive retry mode with up to 10 attempts.
  botocore 1.44.0 made the standard retry mode (3 attempts) the default, so
  throttled `GetProducts` calls failed and the vendor was skipped (#185)
- Progress bars of a failed vendor are cleaned up: the progress bars of its
  interrupted steps are removed from the display and its elapsed timer is
  stopped, instead of counting up while later vendors are being processed. No
  work was left running, only the display was stale. Task ids are no longer
  shared between vendors (#185)
- `azure`: the low memory `l` sizes of the D and F families and the memory
  intensive `m` sizes of the F family are their own series, e.g. `Dldsv5`
  instead of `Ddsv5` and `Famsv6` instead of `Fasv6`, as in the Microsoft docs.
  The M sizes with an extra number before the version (`M48ds_1_v3`) are in
  `Mdsv3` and not in the SKU family of the API, the original `M` series has no
  letters (`M` instead of `Ms`), and `Standard_DC8_v2` is in `DCsv2` (#186)

Database migrations:

- Add the above 4 columns to the `server` and `server_scd` tables (#182)

## v0.11.0 (November 16, 2026)

Breaking changes:

- New `ARCHIVED` status for records replaced by another record or deliberately
  dropped, set only by the archive rules in `sc_crawler.archive_rules` (#157)
- `hcloud`: former datacenter regions (`2`–`7`) with their zones and prices,
  and the `app:static_web` benchmark with its scores are `ARCHIVED`. The
  former datacenter ids are dropped from `Region.aliases` (#157)

New features:

- `pull` and `sync` apply the archive rules, also to child records (e.g.
  prices of a region, scores of a benchmark) (#157)
- `copy --exclude-status` to leave out rows by status, e.g. `archived` (#157)
- `archived-by` command to list the rules archiving a record (#157)

Fixes:

- `azure`: manual data for the `southeastasia3` and `taiwannorth` regions
  (#157)
- Dict-type primary keys (e.g. `BenchmarkScore.config`) compared as `JSONB` in
  PostgreSQL (#157)
- `sync --log-changes-path` no longer fails on rows with a dict-type primary
  key (#157)

Database migrations:

- Add the `archive_rule` table (#157)
- Add `ARCHIVED` to the `status` enum (PostgreSQL) (#157)

## v0.10.4 (November 9, 2026)

Breaking changes:

- `gcp`: TPUs are stored with the `NPU` instead of the `TPU` accelerator type.
  `TPU` is kept in the `AcceleratorType` enum for existing records (#174)

New features:

- `NPU`, `FPGA` and `VPU` in the `AcceleratorType` enum (with a migration
  extending the PostgreSQL enum) (#174)

Improvements:

- `aws`: Inferentia, Trainium, Qualcomm AI100 and Habana Gaudi (previously
  `GPU`) are stored as `NPU`, FPGA (`f1`, `f2`) and video transcoding (`vt1`)
  accelerators as `FPGA` and `VPU`. Trainium2 memory is taken from the AWS docs
  (96 GiB per device), as the API reports 512 GiB (#174)
- `azure`: the NP-series FPGAs are stored as `FPGA` (#174)
- `alicloud`: FPGA, video transcoding and AI accelerators are stored as
  `FPGA`, `VPU` and `NPU` instead of `GPU` (#174)
- The `nvidia_smi` and `nvbandwidth` inspector tasks are skipped on all non-GPU
  accelerators (#174)

Database migrations:

- Add `NPU`, `FPGA` and `VPU` to the `acceleratortype` enum (PostgreSQL) (#174)

## v0.10.3 (November 6, 2026)

New benchmarks:

- `nvbandwidth:slot:local_copy`: per-GPU VRAM copy bandwidth (nvbandwidth
  v0.7+) (#166)

Improvements:

- `Server.family`, `Server.series`, `Database.family` and `Database.series`
  for `gcp`, `hcloud`, `alicloud`, `upcloud`, `ovh`, `vultr`, `aws` and
  `azure`. `family` is the broad workload class in the vendor's own naming,
  `series` the hardware line and generation (#159)
- `Server.compatible_storage_ids` and `Database.compatible_storage_ids` for
  the same vendors (`None` if unknown, `[]` if no extra storage can be
  attached) (#159)
- `family` and `series` column comments of the server and database tables
  updated by an Alembic migration (#159)
- `aws`: the instance family comes from the Pricing API
  `instanceFamilyCategory`, with a docs based fallback (#159)
- `azure`: disk and PostgreSQL storage compatibility derived from the VM
  capabilities and the PostgreSQL capabilities API (#159)
- Database `series` matches the server `series` where a database runs on a
  known server type (`gcp` lowercase machine series, `azure` server series
  built like the database series) (#159)
- One `family` spelling across vendors: `General Purpose` (`alicloud`) and
  `High Performance Computing` (`aws`, `azure`, `alicloud`) (#159)
- `alicloud`: family of the retired `sn1`, `sn2`, `c4`, `ce4`, `cm4`, `n1`,
  `n2` and `e3` types from the docs (the API has no category for them);
  `azure`: `FPGA Accelerated` family for the `PB` sizes (#159)
- `upcloud`: the retired `HICPU` and `HIMEM` plans keep their `High CPU` and
  `High Memory` family (#159)
- `vultr`: no `series` for bare metal plans (#159)
- `alicloud` (disk categories), `aws` (instance categories): API errors are
  handled with the Sentry wrapper instead of being logged (#159)
- `ovh`: flex flavors listed as separate servers (#165)

Fixes:

- Inspector: a server's benchmark results are loaded from other hardware
  variants when variant `0` has no successful run of that benchmark (e.g.
  pgbench runs that landed on newer Azure hardware) (#176)
- `ovh`: October 2026 pricing update (separately billed IPv4 for all instance
  ranges, and local storage for Gen3) (#165)
- `azure`: no Flexible Server sizes invented from the VM catalog when Retail
  only has a per-vCore series meter (e.g. `DCasv5` / `Dsv6`); series meters
  remain for pricing (#172)
- `azure`: ConfidentialVM Flexible Server SKUs only from ACC regions (West
  Europe / UAE North), without billing-only Retail series that are not in the
  capabilities (e.g. `Mdsv2`) (#172)
- `azure`: PostgreSQL compute priced from the `1 vCore` meter (as the pricing
  page does), as some sized meters are stale (#169)
- `azure`: the `newzealandnorth` region is enabled again (#169)
- `nvbandwidth`: correct `p2p:duplex` score and `gpu_count` for v0.6+ stacked
  bidirectional matrices (#166)
- `nvbandwidth`: aborted runs (with `error` in the output) are skipped (#166)
- `nvbandwidth`: environment field `cuda_runtime_version` renamed to
  `cuda_version` (#166)
- `aws`: `t1` and `*-flex` (e.g. `r8i-flex`) instance types are burstable
  instead of dedicated CPU allocation (#168)
- `hcloud`: sold out server types (e.g. `cx23`–`cx53`) stay `ACTIVE`, only
  their per-location prices are `INACTIVE` (#170)
- `hcloud`: server types removed from the API (e.g. `cx11`–`cx52`) are
  `RETIRED` instead of `INACTIVE` (#170)
- `aws`: the instance-level network bandwidth for instance types with
  multiple network cards instead of the first card only (e.g. `p5.48xlarge`
  3200 instead of 100 Gbps). `Server.network_speed_baseline` and
  `network_speed_max` are documented as aggregated over all network cards
  (column comments updated by a migration) (#170)
- `aws`: the SATA SSD instance store of e.g. `c3`, `i2`, `m3`, `r3`, `x1`
  and `x1e` is stored as `SSD` instead of `NVMe SSD` (#170)
- `aws`: instance types not offered (and without spot prices in the past 7
  days) are `RETIRED` if they have no Reserved terms in the price list (e.g.
  `f1`, `g3`, `p2`, `p3`), and keep their on-demand and last known spot prices
  as `INACTIVE` (#170)
- `gcp`: E2 shared-core machines (`e2-micro`, `e2-small`, `e2-medium`) are
  priced for their billed fractional vCPU (0.25, 0.5, 1) instead of 2 vCPUs
  (#170)
- `gcp`: the 14,000 GiB Titanium SSD disks of `z4m` (and 7,000 GiB of
  `z4d-highmem-384-standardlssd-metal`) for storage size and the bundled Local
  SSD price, instead of 375 GiB (#170)
- `gcp`: the renamed C2 SKUs ("Compute optimized Core running in ...") are
  parsed, so `c2-standard` is priced in all regions again (#170)
- `gcp`: the boot Persistent Disk is skipped by its model name instead of
  position in the inspected local NVMe disks (e.g. `a3-highgpu-8g`,
  `c4-*-lssd`) (#170)
- `alicloud`: the GPU memory of other instance types with the same GPU when
  `GPUMemorySize` is missing (e.g. 24 GiB for the A30 of `ecs.gn7s`), and
  unknown instead of 0 otherwise (#170)
- `alicloud`: GPU memory in GiB instead of MiB in server descriptions (#170)
- `alicloud`: out of stock (`WithoutStock`) instance types stay `ACTIVE`, only
  their per-zone prices are `INACTIVE` (#170)
- Unknown `accelerator_memory_total` stays unknown instead of 0 when the
  inspector has no GPU data (e.g. GCP `tpu7-standard-*`, UpCloud B300 plans)
  (#170)
- `upcloud`: the storage of multi-node legacy managed database plans is stored
  per node instead of divided by the node count (e.g. `2x16xCPU-64GB-1000GB`:
  1074 instead of 537 GB) (#170)
- `upcloud`: the longest available backup tier (e.g. 31 days with the
  extended tier) as `continuous_backups` of flexible managed database plans
  (#170)
- `ovh`: all disks of a flavor are counted (e.g. `bm-s1`: 2x 960 GB,
  `h100-1520`: 4x 3840 GB passthrough NVMe besides the system disk) (#170)
- `ovh`: flavors available in the project are `ACTIVE` even without the
  `active` catalog tag (e.g. `t1`, `t2`), and server prices are `INACTIVE` in
  regions where the flavor is not available (#170)
- `ovh`: only managed database engine versions still on sale are listed (e.g.
  no PostgreSQL 14 after its end of sale) (#170)
- `azure`: the temp disk size (`MaxResourceVolumeMB`) is read as MiB instead of
  MB (e.g. `D2ds_v5`: 81 instead of 77 GB) (#170)
- `azure`: GPU count, model and memory from a per-series table based on the
  docs instead of name heuristics, falling back to the API's GPU count (e.g.
  `ND128isr_NDR_GB200_v6`: 4 instead of 1 GPU, `NCC40ads_H100_v5`: 1 instead
  of 0, `NC24lds_xl_RTXPRO6000BSE_v6`: 1/4 instead of 4). `NP` FPGAs are no
  longer counted as GPUs (#170)
- `azure`: GPU memory read as GiB instead of GB (e.g. H100: 80 instead of 74.5
  GiB) (#170)
- `azure`: the `Dv3`, `Dsv3`, `Ev3` and `Esv3` series are
  `PLANNED_FOR_RETIREMENT` (retiring on November 15, 2029) (#170)
- `azure`: only PostgreSQL Flexible Server series that the capabilities API
  supports in at least one region are listed, so the retail meters of
  unsupported series (e.g. `DCasv5`, `Dsv6`, `Ebdsv5`, `Mdsv2`) no longer add
  database SKUs (#170)
- `azure`: PostgreSQL SKU status no longer inherits the VM size retirements
  (e.g. `B1ms` is `ACTIVE`, not `PLANNED_FOR_RETIREMENT`) (#170)

## v0.10.2 (October 22, 2026)

New features:

- Duration (seconds) of the benchmarking framework run in
  `BenchmarkScore.environment.duration` (#160)
- `upcloud`: flexible DBaaS plan create args in
  `Database.api_reference_object` (`plan_node_counts`, `plan_backups`,
  `plan_storage.step_gib` / `options` bands from `GET /1.3/database/plans`),
  so consumers can snap `plan_storage_gib` without a schema change (#164)

Fixes:

- `aws`: the new RDS `UnusedBox` products (no instance family, vCPU, or
  memory) are skipped (#162)

## v0.10.1 (October 20, 2026)

New benchmarks:

- stress-ng stressor results (`stress_ng:<method>`) from the
  `stressng_benchmarks` inspector task (#152)

Improvements:

- `hcloud`: the server type `category` as server family (#145)

Fixes:

- `hcloud`: `/v1/locations` instead of the deprecated `/v1/datacenters`, with
  the location name as region id (former datacenter region ids kept in
  `aliases`) (#145)
- `hcloud`: deprecated CCX Gen1 plans (`CCX11`–`CCX51`) are Intel (#145)
- `Server.api_reference_object` filled with Pulumi/Terraform provisioning args
  for `aws`, `azure`, `gcp`, `alicloud`, `upcloud`, `vultr` and `hcloud`
  (`ovh` left `NULL`, as `flavor_id` is region-specific) (#154)
- Standard `RTX PRO 6000` naming and family (`Blackwell`), and `RTX 6000`
  family by memory (`Ada Lovelace` or `Turing`) (#154)
- `aws`: `accelerator_type` of spot-only `ACTIVE` GPU servers (#149)

## v0.10.0 (October 8, 2026)

Breaking changes:

- The `gpu_*` columns of `Server` renamed to `accelerator_*`, as they also
  cover other accelerator types such as TPUs: `accelerator_count`,
  `accelerator_memory_min`, `accelerator_memory_total`,
  `accelerator_manufacturer`, `accelerator_family`, `accelerator_model`, and
  `accelerators`. The `Gpu` JSON model is renamed to `Accelerator` (#146)

New features:

- `Server.accelerator_type` (`AcceleratorType` enum: `GPU` or `TPU`) for the
  type of the primary accelerator. `gcp` TPU machine types are marked as
  `TPU`, all other vendors' accelerators (and the ones found by `nvidia-smi`)
  as `GPU` (#146)
- Optional `compatible_storage_ids` JSON column in `Server` and `Database`,
  listing the `storage_id`s (or `database_storage_id`s) that can be attached as
  extra storage (not populated yet) (#146)
- `Benchmark.environment_fields` JSON column documenting the keys recorded in
  `BenchmarkScore.environment`, similar to `config_fields` (#146)
- Optional `Benchmark.subcategory` column for grouping benchmarks within a
  category, e.g. the nvbandwidth scopes or Passmark CPU / Memory tests (#146)
- Optional `series` column in `Server` and `Database` for a sub-type within
  the `family` (not populated yet) (#146)
- Optional `Server.api_reference_object` JSON column (not populated yet), as
  already available for `Database` (#146)

Fixes:

- `BenchmarkScore.observed_at` is the crawl timestamp (like in other tables).
  The end of the benchmark run is recorded in `environment.measured_at` (#146)
- Benchmark category changes: `redis:*` moved to `Database`, and `openssl` to
  `Cryptography` (#146)
- Missing values of optional JSON columns stored as `NULL` instead of the JSON
  `null` literal (existing records are kept as is) (#146)
- The `nvidia_smi` and `nvbandwidth` inspector tasks are skipped on TPU
  machines (#146)

Maintenance:

- Storages inventoried before servers, and database storages before
  databases (#146)

Database migrations:

- Rename the `gpu_count`, `gpu_memory_min`, `gpu_memory_total`,
  `gpu_manufacturer`, `gpu_family`, `gpu_model` and `gpus` columns of the
  `server` table to `accelerator_*` and `accelerators` (#146)
- Add the `accelerator_type` (with the new `acceleratortype` enum),
  `api_reference_object`, `series` and `compatible_storage_ids` columns to the
  `server` table (#146)
- Add the `series` and `compatible_storage_ids` columns to the `database` table
  (#146)
- Add the `environment_fields` and `subcategory` columns to the `benchmark`
  table (#146)
- Convert the `cpu_flags`, `cpus`, `accelerators` and `storages` columns of the
  `server` table from `JSON` to `JSONB` (PostgreSQL)

## v0.9.5 (October 8, 2026)

New features:

- Inspector task block reasons for databases (#148)

## v0.9.4 (October 7, 2026)

Fixes:

- `upcloud`: flexible `rdb.*` Developer / Standard / High Memory PostgreSQL
  plans inventoried from `/database/plans`. The managed DB storage id
  `additional-disk` is replaced with `standard` (Developer plans and legacy
  additional disk) and `maxiops` (Standard / High Memory plans), matching the
  block-storage storage ids (#144)
- `ovh`: server offers without a public catalog price are skipped and repeated
  flavor/region offers deduplicated. Regions without instances or managed
  databases (e.g. `RBX-ARCHIVE`) are skipped, IPv4 prices listed only in
  compute regions and block storage prices only where the volume type is
  offered (#144)

## v0.9.3 (October 2, 2026)

New benchmarks:

- nvbandwidth (#137)

New features:

- Inspector task ruleset, ported from `sc-inspector` (#143)

Fixes:

- `gcp`: Compute Engine prices and GPU/TPU naming checked against the Billing
  Catalog SKUs. On-demand and spot prices cover `z4d`, `ct5l`, `ct5lp`,
  `ct5p`, `ct6e`, and `tpu7x`, plus specialized Core/Ram families, GPU slice
  SKUs, GBy.h memory units, and bundled Local SSD GiB-month rates. TPU models
  use `v3` / `v5e` / `v5p` / `v6e` / `v7x` (#140)
- Vendor API storage kept when the inspector has no disk sample (e.g. GCP
  `z4d`) (#140)
- `aws`: correct parsed EBS max IOPS, throughput, and size (#136)
- `azure`: PostgreSQL Flexible Server SKUs from the retail prices (#138)

Maintenance:

- Database inventories for `ovh`, `upcloud` and `vultr` (#122)
- `StorageType.NETWORK` removed: the former network-attached block storage is
  mapped to media/performance classes (`HDD` / `SSD` / `NVME_SSD`) instead
  (#139, #142)
- `gcp`: Hyperdisk types warehoused into `storage` (capacity prices), and max
  IOPS/throughput for Persistent Disk and Hyperdisk from the docs (#141)
- Example API responses commented next to vendor requests, and those calls
  moved into helper functions (#135)
- Benchmark unit tests merged into `tests/test_benchmarks.py` (#137)

## v0.9.2 (August 17, 2026)

New features:

- `PLANNED_FOR_RETIREMENT` and `RETIRED` in `Status` for `Server` and
  `Database` (model validators reject these on other tables) (#121)
- Vendor inventory mapped onto those statuses from confirmed APIs and docs
  (#121)

Database migrations:

- Add `PLANNED_FOR_RETIREMENT` and `RETIRED` to the `status` enum (PostgreSQL)
  (#121)

## v0.9.1 (August 14, 2026)

Breaking changes:

- `benchmark_score` responses expose `environment` as an object;
  `kernel_version` / `database_engine_version` are no longer top-level fields
  (#120)
- `pgbench:heavy_read_only` ingest reshaped: `concurrency` is an integer (one
  raw score per profile point). The old string configs `"single"` / `"peak"`
  move to the config-less `pgbench:heavy_read_only:single` and
  `pgbench:heavy_read_only:peak` (#120)

New features:

- pgbench scores record `latency_avg_ms` (plus `peak_concurrency` on the peak
  row) in `environment` (#120)

## v0.9.0 (August 10, 2026)

Breaking changes:

- `benchmark_score` reshaped: a `resource_type` discriminator and
  `resource_id` (replaces `server_id`); an extensible `environment` JSON column
  (e.g. `kernel_version`, `database_engine_version`) replaces `kernel_version`
  (#119)

Fixes:

- `ovh`: correct charges for stopped servers (#117)
- `ovh`: note that billing of stopped servers depends on the location (#117)
- `azure`: outdated server prices explicitly excluded before the most recent
  record takes precedence (#117)
- No bogus CPU cache amount for ARM servers whose hypervisor reports zero
  (#117)

Maintenance:

- The empty `database_benchmark_score` table dropped; database scores use
  `benchmark_score` with `resource_type=DATABASE` (#119)
- `server_id` / `database_id` query and insert keys kept via hybrid
  properties and input-dict translation (#119)
- `pgbench` scores ingested for database instances too (#119)

Database migrations:

- Add the `resource_type` column to the `benchmark_score` table, rename its
  `server_id` column to `resource_id`, and replace `kernel_version` with the
  `environment` JSON column. Existing rows are server scores (#119)
- Drop the `database_benchmark_score` table (#119)

## v0.8.5 (July 31, 2026)

New benchmarks:

- pgbench (#116)

Fixes:

- `aws`, `azure` and `gcp`: corrected and filled PostgreSQL DBaaS inventory
  fields (HA levels and strategies, storage bounds, monitoring, backups, SLA,
  and related capabilities) (#111)
- `aws`: non-orderable RDS instance classes kept in the catalog as `INACTIVE`
  (prices still crawled) (#111)
- `alicloud`: API timeout and region mapping updates (#111)
- `gcp`: no hardcoded `SERVER_FAMILIES` allowlist gating newer (missed) server
  pricing lookups. Families with no pricing SKUs yet in the Billing Catalog
  (e.g. `A4X`, `M4N`, `X4`, TPU VM series as of 2026-08) are skipped (logged
  at DEBUG) instead of throwing an exception (#113)
- `gcp`: `cpu_architecture` read from the `MachineType.architecture` API field.
  It was hardcoded to recognize only `t2a` as `ARM64`, so every other series
  (including the Arm-based Axion `c4a`/`n4a`) defaulted to `X86_64` (#112)

Maintenance:

- `Database` table refactored: `ha_supported` replaced with the ordered JSON
  lists `ha` (`DatabaseHaLevel`) and `ha_strategy` (`DatabaseHaStrategy`),
  `storage_autoscaling` renamed to `storage_extra_autosize`, `support_level`
  dropped, and capability fields added (`wire_protocol`, storage bounds,
  monitoring, `autotuning_advice` / `autotuning_apply`, and
  `security_features`) (#111)
- Optional `Database.api_reference_object` (JSON): named API args identifying
  the database instance when known (#114, #111)
- `ha` and `ha_strategy` (scalar enums) in the `database_price` primary keys,
  so HA deployments can carry distinct prices (e.g. AWS Multi-AZ, Azure 2x HA
  compute, GCP Regional meters). The catalog `database.ha` / `ha_strategy`
  remain ordered JSON lists (#111)

Database migrations:

- Refactor the `database` table as described above: replace `ha_supported`
  with `ha` and `ha_strategy`, rename `storage_autoscaling` to
  `storage_extra_autosize`, drop `support_level`, and add the new capability
  columns and `api_reference_object` (#111)
- Add `ha` and `ha_strategy` to the primary key of the `database_price` table
  (#111)

## v0.8.4 (July 28, 2026)

New features:

- `aws`: PostgreSQL DBaaS support (#108)
- `database_benchmark_score` table for database benchmark results, mirroring
  `benchmark_score` (#106)

Database migrations:

- Add the `database_benchmark_score` table (#106)

## v0.8.3 (July 15, 2026)

New features:

- PostgreSQL DBaaS catalog tables: `database`, `database_price`,
  `database_storage`, and `database_storage_price`, with SCD mirrors and an
  Alembic migration (#104)
- Initial `inventory_databases`, `inventory_database_prices`,
  `inventory_database_storages`, and `inventory_database_storage_prices`
  methods for selected vendors (now `azure` and `gcp`). Records collected
  through this beta release are not yet intended for production use, only for
  initial exploration (#104)

Fixes:

- `upcloud`: region availability checked for GPU and GPU spot instance prices
  before adding them (#101)
- `static_web` benchmark measurement unit changed from kB to KiB (#102)

Database migrations:

- Add the `database`, `database_price`, `database_storage` and
  `database_storage_price` tables (#104)

## v0.8.2 (June 30, 2026)

Maintenance:

- `impact_formula` field in the `CompoundSource` of the `Benchmark.source`
  model: a human-friendly explanation of the formula used to calculate the
  impact of the benchmark components on the overall workload score (#98)
- `impact` field in the `ScoreComponent` of the `BenchmarkScore.score_breakdown`
  model: how much a benchmark component raised or lowered the overall workload
  score (#98)
- Redundant `benchmark_id` and `config_filter` fields dropped from the
  `ScoreComponent` of the `BenchmarkScore.score_breakdown` model, as they can be
  derived from the `Benchmark.source` model (#98)
- Raw, normalized, and impact scores rounded (#98)

## v0.8.1 (June 29, 2026)

Fixes:

- Non-nullable `description` field in the `Server` table (#96)

Database migrations:

- Make the `description` column of the `server` table non-nullable (#96)

## v0.8.0 (June 29, 2026)

New features:

- `Benchmark.source` JSON column: a discriminated provenance descriptor
  (`measured`, `extrapolated`, or `compound`) describing how each benchmark
  score is produced, including component recipes and aggregation/normalization
  methods for workload profiles (#92)
- `Benchmark.note` column for optional interpretation caveats (warning/info
  badges), e.g. scaling limits on high-vCPU instances (#92)
- `BenchmarkScore.score_breakdown` JSON column: per-server structured
  derivation of composite workload profile scores (component raw values, fleet
  medians, normalized ratios, weights, and coverage) (#92)
- Declarative per-component missing-data policies (`ignore`, `penalize`,
  `require`) on workload profile definitions, with a `penalty` floor for
  penalized components; `require`/`penalize` rules applied to LLM inference
  workload entries (#92)

Fixes:

- Benchmark scores for the workload profiles (v2) normalized with median
  ratios instead of min-max scaling (#92)
- Weighted average of workload profile (v2) scores computed with the geometric
  mean instead of the arithmetic mean (#92)
- Benchmark components that don't scale well on 32+ vCPUs removed from
  workload profile (v2) scores: `geekbench`, `passmark:database_operations`,
  `passmark:memory_latency` (#92)
- Computer vision and memory latency benchmarks removed from the mixed
  inference workload, for an LLM-focused, more useful and fairer score (#92)
- Static web scaling caveat moved from the benchmark descriptions into the
  `note` field (#92)
- `vultr` and `ovh`: filled and corrected `description` fields in the `Server`
  table (#93)

Database migrations:

- Add the `source` and `note` columns to the `benchmark` table, and the
  `score_breakdown` column to the `benchmark_score` table (#92)

## v0.7.0 (June 22, 2026)

New vendors:

- Vultr (`vultr`) (#85)

New features:

- `ServerDescription` table, filled with generated descriptions from
  `sc-navigator-descriptions` during the server inventory (#91)

Fixes:

- `Server.average_time_to_start` data harvesting (#88)
- Correct NULL/0 handling for `gpu_memory_min` and `gpu_memory_total` in vendor
  scripts (#88)

Database migrations:

- Add the `server_description` table (#91)

## v0.6.0 (June 3, 2026)

Breaking changes:

- `Server.network_speed` renamed to `network_speed_baseline` (#83)

New features:

- `metadata` command to read and write database metadata (#79)
- `membench` benchmark scores with `scope: RAM` config for the first working
  set size per operation that exceeds the total CPU cache (L3, else L2, else
  L1d) (#80)
- `stopped_server_charged`, `billing_increment_seconds`,
  `minimum_billing_seconds` and `billing_comment` columns in the `Vendor`
  table, filled for all vendors (#81)
- `ecpus`, `scalability`, `hw_virt`, `memory_amount_actual`,
  `network_speed_max`, `network_storage_speed_baseline`,
  `network_storage_speed_max` and `average_time_to_start` columns in the
  `Server` table, filled for all vendors (network speeds on a best effort
  basis) (#83)

Fixes:

- `upcloud`: missing GPU-related data of the GPU family servers (#82)

Database migrations:

- Add the `stopped_server_charged`, `billing_increment_seconds`,
  `minimum_billing_seconds` and `billing_comment` columns to the `vendor` table
  (#81)
- Add the `ecpus`, `scalability`, `hw_virt`, `memory_amount_actual`,
  `network_speed_max`, `network_storage_speed_max`,
  `network_storage_speed_baseline` and `average_time_to_start` columns to the
  `server` table, and rename its `network_speed` column to
  `network_speed_baseline` (#81)

## v0.5.1 (April 22, 2026)

New features:

- Workload profile scores: precomputed composite `BenchmarkScore` rows that
  combine multiple raw benchmark results into a single normalized score per
  server for five predefined workload profiles (`web`, `compute`, `cache`,
  `ml`, `cicd`), each using a weighted mix of benchmark components (#71)
- `Benchmark.category`, filled for the existing benchmarks (#73)

Fixes:

- Python 3.14 support: the `pydantic` dependency is unpinned and
  `pydantic.ImportString` replaced with a standard Python alternative in the
  table definitions (#68)
- Sentry error tracking in the region and zone inventories (#70)
- `alicloud`: hourly-rated storage prices converted to monthly (#72)
- `azure`: storage price units converted to $/GB/month for all supported unit
  types, and the storage meter mapping covers all P1-P80, E1-E80, and S4-S80
  disk sizes across LRS and ZRS redundancy tiers (#72)
- `min_size`, `max_size`, and `max_throughput` calculations in the vendor
  modules and the column descriptions of the `Storage` table in GB and MB/s
  (#73)

Database migrations:

- Add the `category` column to the `benchmark` table (#73)

## v0.5.0 (March 23, 2026)

Breaking changes:

- `benchmark_score` table refactored: new `framework_version` and
  `kernel_version` columns, with the `config_fields` and `config` columns and
  the benchmark data digest updated accordingly. The data migration from
  `config.framework_version` to the `framework_version` column is implemented
  for both PostgreSQL and SQLite, but in SQLite the `framework_version` field
  is not removed from the config JSON (#65)

Fixes:

- Old `Benchmark` records phased out as `INACTIVE` (#61)
- `gcp`: `lsblk` storage data, with `lshw` as a fallback (#63)
- `ovh`: storage info parsing extended with NVMe devices from the API data
  (#63)
- `compression_text` benchmark scores: the `threads` config field refactored to
  `cores` (`single/multi`) (#64)
- `geekbench` benchmark scores: the `cores` config field refactored to
  `single/multi` (#64)

Database migrations:

- Add the `framework_version` and `kernel_version` columns to the
  `benchmark_score` table, and move `framework_version` from `config` to the new
  column (#65)

## v0.4.0 (March 14, 2026)

Breaking changes:

- `cpu_l1_cache` removed; replaced by `cpu_l1d_cache` and `cpu_l1i_cache`
  (per-core KiB) (#60)
- `cpu_l2_cache` and `cpu_l3_cache` unit changed from total bytes to per-core
  KiB (#60)

New benchmarks:

- membench (#59)

Fixes:

- CPU cache columns refactored: the old `cpu_l1_cache` (total bytes) split into
  separate per-core KiB columns `cpu_l1d_cache` and `cpu_l1i_cache`;
  `cpu_l2_cache` and `cpu_l3_cache` converted from total bytes to per-core KiB;
  new `cpu_l1d_cache_total`, `cpu_l1i_cache_total`, `cpu_l2_cache_total`, and
  `cpu_l3_cache_total` columns store the total cache size in KiB across all
  cores (#60)
- `lstopo` output as the primary source for L1/L2/L3 CPU cache sizes, falling
  back to `lscpu` only when no `lstopo` data is available (#60)

Database migrations:

- Replace the `cpu_l1_cache` column of the `server` table with
  `cpu_l1d_cache` and `cpu_l1i_cache`, add the `cpu_l1d_cache_total`,
  `cpu_l1i_cache_total`, `cpu_l2_cache_total` and `cpu_l3_cache_total` columns,
  and convert the existing values to KiB (#60)

## v0.3.6 (February 26, 2026)

New features:

- `__version__` and `__version_info__` variables in the package (#58)

## v0.3.5 (February 26, 2026)

Breaking changes:

- Python 3.11 or later required, up from 3.9 (#53)

New features:

- Monthly cap of on-demand prices (#49)

Fixes:

- `azure`: Denmark East region (Copenhagen) (#50)
- Correct SCD table schema generation in the CLI `create` command (#51)
- Deprecated `datetime.utcnow()` calls replaced with `datetime.now(UTC)` (#52)
- Field deserializers and reconstructors for the `cpus`, `gpus`, `storages`,
  and `price_tiered` columns, to prevent Pydantic serialization warnings and to
  keep the original data types when loading from the database (#56)
- Correct and extended test cases for field serializers and the OVH vendor
  module (#52)
- `aws`: Provisioned IOPS (io1, io2) storage types, and updated gp3 volume
  limits (IOPS, throughput, size) (#53)
- `DynamicDocstrings` griffe extension accepts the new `agent` keyword argument
  of griffe 0.49.0 (#56)
- `mkdocs<2.0` pinned, as MkDocs 2.0 is incompatible with Material for MkDocs
  (#56)
- No `mkdocs` build warnings and version incompatibilities (#56)

## v0.3.4 (February 5, 2026)

New features:

- CLI tool to dump database tables to JSON files (#43)
- `alicloud`: spot instance price sampling (#46)
- Fractional GPU counts for servers with partial GPU allocation (#48)

Fixes:

- `gcp`: storage info from the lshw outputs (#39)
- `alicloud`: region availability checked before adding server prices (#41)
- `alicloud`: CPU allocation type of servers (#42)
- Vendor API data preserved by default, only overridden when necessary for
  known API data issues (#45)
- `alicloud`: instance type retirement status verified (#47)
- No duplicate records inserted into the database (#48)

Maintenance:

- Delayed method validation, to avoid a slow CLI startup (#44)
- No name conflicts in vendor modules, via private modules (#44)
- All prices converted to float and rounded to 4 digits (#47)
- `gpu_count` field type changed from integer to float for fractional GPU
  support (#48)
- Foreign key constraints removed from the SCD table definitions (#48)
- Alembic revision history reset, and the initial migration script rewritten
  (#48)

Database migrations:

- Reset the migration history: the new initial migration (`dad8a1f0f455`)
  creates all tables (#48)
- Change the `gpu_count` column of the `server` table from integer to float
  (#48)

## v0.3.3 (January 2, 2026)

New vendors:

- Alibaba Cloud (`alicloud`) (#37)

Fixes:

- L1 cache size without the instruction cache (#38)
- Manufacturer of Ampere Altra (#37)

## v0.3.2 (December 4, 2025)

New vendors:

- UpCloud (`upcloud`) (#33)
- OVHcloud (`ovh`) (#36)

New benchmarks:

- PassMark (#31)
- LLM inference speed

Fixes:

- Minor region and server detail overrides

## v0.3.1 (October 25, 2024)

New benchmarks:

- Static HTTP server (#28)
- Redis (#28)
- stress-ng's div16 run on all vCPUs

New features:

- Optional list of tables to sync in the CLI tool
- Standardized CPU and GPU manufacturer, family, and model names
- Optional description for disks

Fixes:

- Better support for long-running DB syncs
- `gcp`: the dummy "2 Ghz" CPU speed is excluded
- Better physical CPU cores lookup
- Faster interactive bulk inserts
- Storage sizes reviewed for vendors that report them in base 2 or base 10
- `azure`: the deprecated API endpoint replaced, and NVMe drives ingested
- `azure`: better support for API rate limits

## v0.3.0 (August 20, 2024)

Breaking changes:

- Complex queries with joins relying on the foreign keys of the table
  definitions use the right references. This might give different (but
  correct) results than before (#25)

New vendors:

- Microsoft Azure (`azure`) (#25)

New features:

- `hcloud`: the new CX server types
- `hcloud`: the new Singapore region
- Better caching

Fixes:

- Join references point to the right tables (#25)
- CPU cores counted in all physical CPUs
- Better standardization and cleanup of the CPU manufacturer, family, and model
  (#24)
- CPU speed extracted from the CPU description when available, instead of the
  unreliable `dmidecode` data (#24)
- `hcloud`: included outbound network extractor updated for an API change (#24)
- `gcp`: server availability in a zone checked even when a related price is
  known
- No `SAWarning` on multiple relationships that use overlapping compound
  foreign keys (#25)
- `gcp`: corrected manually collected geolocation of 3 regions
- Spelling of the benchmark and table column descriptions

## v0.2.1 (June 4, 2024)

Fixes:

- `dict` values sorted by key before being passed as JSON to the database
  engine (#23)

## v0.2.0 (June 4, 2024)

Breaking changes:

- Datacenter renamed to Region in all tables and across the codebase (#22)

Database migrations:

- Name all constraints for easier management in the future (#22)
- Rename the `datacenter` table to `region`, and the `datacenter_id`
  column to `region_id` in the `zone`, `server_price`,
  `storage_price`, `traffic_price` and `ipv4_price` tables (#22)

## v0.1.4 (June 2, 2024)

Breaking changes:

- The `memory` column of the `server` table renamed to `memory_amount` (#21)

New features:

- Documented `benchmark` workloads and actual `benchmark_score` records loaded
  from `sparecores-inspector-data` (#21)
- Enriched `server` details loaded from `sparecores-inspector-data` (#21)

Database migrations:

- Add the `benchmark` and `benchmark_score` tables (#21)
- Add 8 new columns to the `server` table (#21)

## v0.1.3 (May 7, 2024)

New features:

- `api_reference` and `display_name` in `Datacenter`, `Zone`, and `Server`
  (#20)
- Latitude and longitude coordinates in `Datacenter` (#20)
- `Server.family` (#20)

Database migrations:

- Add the `api_reference` and `display_name` columns to the `datacenter`,
  `zone` and `server` tables, filled from `name` for the existing rows (from
  `datacenter_id` for the `aws` datacenters) (#20)
- Add the `lon` and `lat` columns to the `datacenter` table (#20)
- Add the `family` column to the `server` table (#20)

## v0.1.2 (April 24, 2024)

New vendors:

- Google Cloud Platform (`gcp`) (#19)

New features:

- SVG logo for all supported vendors (#19)

Fixes:

- `aws`: the missed outbound traffic prices (#19)
- `hcloud`: outbound traffic price per GB instead of TB (#19)
- `hcloud`: `datacenter_id` reference in the server prices table (#19)

## v0.1.1 (April 12, 2024)

Breaking changes:

- As the database migration tool was just introduced, databases already
  initialized with SC Crawler (e.g. with data collected in SCD tables) need to
  be stamped for Alembic as being on v0.1.0:

  ```sh
  sc-crawler schemas stamp --revision 98894dffd37c
  ```

New vendors:

- Hetzner Cloud (`hcloud`) (#18)

New features:

- Database migration helpers in the CLI (#18)
- The CREATE TABLE generator subcommand moved under `schemas create` (#18)

Maintenance:

- Alembic for database migrations (#18)

Database migrations:

- Add the `description` field to `Server` (#18)
- Make `Server.cpu_cores` optional (#18)

## v0.1.0 (April 5, 2024)

New vendors:

- Amazon Web Services (`aws`)

New features:

- Initial PyPI release of `sparecores-crawler`
- CLI tools:
  - Database schema generation for the standard and SCD tables of the
    supported records in various SQL dialects
  - Records pulled from vendor APIs into a database
  - All supported tables copied from a database into another one
  - Records of a database synced into another database's standard or SCD
    tables, with optional logging of the changes
  - Hashes of the database content
- Supported records: `country`, `compliance_framework`, `vendor`,
  `vendor_compliance_link`, `datacenter`, `zone`, `server`, `server_price`,
  `storage`, `storage_price`, `traffic_price` and `ipv4_price`

Maintenance:

- Package documentation via MkDocs, Material for MkDocs, `mkdocstrings`, and
  other MkDocs plugins
- Database documentation on table schemas, relations and column comments via
  DBML and dbdocs
- Unit tests via `pytest`
- Linting via `ruff`
