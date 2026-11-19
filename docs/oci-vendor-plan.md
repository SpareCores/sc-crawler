# Plan: Oracle Cloud Infrastructure (OCI) vendor support

Status: server and database inventories are implemented on the
`dev-280-vendor-data-source-oracle-cloud-infrastructure` branch (not pushed). A live
pull into `sc-data-oci.db` ran clean on 2026-11-16.

Last reviewed: 2026-11-13 (servers) and 2026-11-16 (databases, §3.11), against the live API of our tenancy (home region
`eu-frankfurt-1`, also subscribed to `us-ashburn-1` and `us-phoenix-1`), the public
price list (`lastUpdated: 2026-11-02`) and the Oracle docs linked below.

Each fact is marked with how it was checked:

- **[API]**: seen in a live response of our tenancy.
- **[docs]**: read on the linked official Oracle page.
- **[unverified]**: not confirmed from an official source in this review.

---

## 1. Summary of the approach

| Area | Data source | Auth | State |
| --- | --- | --- | --- |
| Regions | `IdentityClient.list_regions` + `list_region_subscriptions`, curated location table | yes | done |
| Zones | `IdentityClient.list_availability_domains` per subscribed region | yes | done |
| Servers | `ComputeClient.list_shapes` per availability domain | yes | done |
| Server prices | Public price list + curated shape series → part number mapping | no | done |
| Spot prices | Fixed 50% preemptible discount on a curated list of VM series | no | done |
| Storages / prices | Curated Block Volume performance levels + price list parts | no | done |
| Traffic prices | Price list outbound parts + region prefix → part mapping | no | done |
| IPv4 prices | Free (no price list part) | no | done |
| Databases | `PostgresqlClient.list_shapes` + `list_default_configurations` per subscribed region, features from docs | yes | done |
| Database prices | Compute shape parts + PostgreSQL fee part | no | done |
| Database storages / prices | Curated performance tiers + Block Volume and Database Optimized Storage parts | no | done |

`vendor_id` is `oci`. The module is `vendors/_oci.py`, so `import oci` in it resolves
to the SDK.

---

## 2. Findings that changed the original plan

1. **`list_shapes` only returns what the tenancy can launch.** [API] Our tenancy sees
   44 distinct shapes over 9 availability domains: Standard (VM and BM), Optimized3,
   and three bare metal Dense I/O / A4 shapes. No GPU, HPC or VM Dense I/O shape is
   listed. The Limits API and `list_compute_capacity_reservation_instance_shapes`
   return `NotAuthorizedOrNotFound` for the crawler user, so the cause (service
   limits) is inferred, not confirmed. See §9, question 1.
2. **Only 3 of 44 regions are subscribed.** [API] Availability domains and shapes
   can be listed only in subscribed regions.
3. **Availability domain names are not uniform.** [API] Frankfurt uses
   `XXXX:EU-FRANKFURT-1-AD-1`, Ashburn `XXXX:US-ASHBURN-AD-1`, Phoenix
   `XXXX:PHX-AD-1`. The zone id is therefore built from the region id and the trailing
   number, not by lower-casing the name.
4. **The price list response differs from its documentation.** [API] The per-currency
   list is in `currencyCodeLocalizations`, not `prices` as the docs page shows.
5. **Tiered parts list the free tier first.** [API] E.g. A1 OCPU is `0` for
   `rangeMin 0..rangeMax 3000`, then `0.01` up to `999999999999999`.
6. **Bare metal has a one-hour minimum charge**, VMs one minute. [docs]
7. **Stopped billing is a per-shape API field** (`is_billed_for_stopped_instance`).
   [API]
8. **Preemptible support is narrower than "most flexible shapes".** [docs] A2, A4.Ax,
   E6.Ax and Standard4.Ax are not on the list.
9. **Burstable is limited to four shapes** (Standard3, E3, E4, E5 Flex) with 12.5% or
   50% baselines. [docs] The API also reports baselines on E6.Flex. [API]
10. **Previous generation shapes have an "end of orderability" date but are still
    fully supported and still listed by the API.** [docs] [API] There is no retirement
    signal, so they stay `ACTIVE`.

---

## 3. Verified base data

### 3.1 `Vendor` instance

| Field | Value | Check |
| --- | --- | --- |
| `billing_increment_seconds` | 1 | [docs] per-second billing release note |
| `minimum_billing_seconds` | 3600 (worst case: bare metal; VMs are 60, in `billing_comment`) | [docs] |
| `stopped_server_charged` | `True` (worst case), exceptions in `billing_comment` | [docs] |
| `founding_year` | 2016 | [unverified] |
| address | 2300 Oracle Way, Austin, TX 78741 | [unverified] |
| `status_page` | `https://ocistatus.oraclecloud.com` | [unverified] |

Stopped instances: billing pauses for Standard shapes, VM Optimized and VM.GPU.A10;
it continues for Dense I/O, HPC, bare metal Optimized and all other GPU shapes.
[docs](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/resource-billing-stopped-instances.htm)

Per-second billing:
[release note](https://docs.oracle.com/iaas/releasenotes/changes/20facdce-34bf-4648-a0a7-de5db73657ce/index.htm).

### 3.2 Credentials and IAM

Environment variables (preferred; all required once `OCI_TENANCY_OCID` is set):
`OCI_USER_OCID`, `OCI_TENANCY_OCID`, `OCI_FINGERPRINT`, `OCI_REGION` (home region),
and `OCI_PRIVATE_KEY` (PEM content) or `OCI_PRIVATE_KEY_PATH`. Otherwise
`~/.oci/config` with the `OCI_CONFIG_PROFILE` profile.

Minimum policy, each verb checked against the IAM policy reference [docs]:

```text
Allow group sc-crawler to inspect tenancies in tenancy         # ListRegions, ListRegionSubscriptions (TENANCY_INSPECT)
Allow group sc-crawler to inspect compartments in tenancy      # ListAvailabilityDomains (COMPARTMENT_INSPECT)
Allow group sc-crawler to inspect instance-family in tenancy   # ListShapes (INSTANCE_INSPECT)
```

The price list needs no authentication.

### 3.3 Regions

`list_regions` returns 44 regions as `{'key': 'FRA', 'name': 'eu-frankfurt-1'}`.
[API] All 44 are in the curated `_REGION_LOCATIONS` table, with names, cities and
countries from the
[regions page](https://docs.oracle.com/en-us/iaas/Content/General/Concepts/regions.htm).
[docs] That page also lists `eu-jovanovac-1`, which is in the OC20 realm and not
returned by our API. Coordinates are city-level. `founding_year` and `green_energy`
are left empty (no per-region source checked).

`list_region_subscriptions` returns
`{'region_key', 'region_name', 'status': 'READY', 'is_home_region'}`. [API]

Regions with 3 availability domains: Frankfurt, London, Ashburn, Chicago, Phoenix.
All others have 1. [docs]

### 3.4 OCPU to vCPU

From the
[compute shapes page](https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm):
[docs]

- x86 (AMD, Intel): 1 OCPU = 2 vCPUs (one core, two threads).
- Arm A1: 1 OCPU = 1 core = 1 vCPU.
- Arm A2 and A4: 1 OCPU = 2 cores = 2 vCPUs.

So `cpu_cores` is the OCPU count on x86 and the vCPU count on Arm. The API is
consistent with this: `BM.Standard.A4.48` has 48 OCPUs. [API]

### 3.5 `Shape` fields

Present in the live response (after `oci.util.to_dict`): [API]

`shape`, `processor_description`, `ocpus`, `memory_in_gbs`,
`networking_bandwidth_in_gbps`, `gpus`, `gpu_description`, `local_disks`,
`local_disks_total_size_in_gbs`, `local_disk_description`, `rdma_ports`,
`rdma_bandwidth_in_gbps`, `is_flexible`, `is_subcore`, `billing_type`
(`PAID` / `LIMITED_FREE` / `ALWAYS_FREE`), `is_billed_for_stopped_instance`,
`is_live_migration_supported`, `baseline_ocpu_utilizations`, `quota_names`,
`platform_config_options`, `resize_compatible_shapes`.

Flexible shapes also have:

- `ocpu_options`: `min`, `max`, `max_per_numa_node`
- `memory_options`: `min_in_g_bs`, `max_in_g_bs`, `default_per_ocpu_in_g_bs`,
  `min_per_ocpu_in_gbs`, `max_per_ocpu_in_gbs`, `max_per_numa_node_in_gbs`
- `networking_bandwidth_options`: `min_in_gbps`, `max_in_gbps`,
  `default_per_ocpu_in_gbps`

There is no lifecycle or preemptible field.

`processor_description` values seen: [API]

```text
2.3 GHz AMD EPYC™ 9J14 (Genoa)
3.0 GHz Intel® Xeon® Gold 6354 (Ice Lake)
2.3 GHz Intel® Xeon® E5-2699 v3 (Haswell)
2.2 GHz Base 3.9 GHz Turbo Intel® Xeon® Platinum 6987C-P (Granite Rapids)
3.0 GHz Ampere® Altra™
3.0 GHz Ampere® AmpereOne™ (Siryn™)
3.6 GHz Ampere® AmpereOne-M™ (Banshee 12™)
AmpereOne-M
```

`gpu_description` was never seen (no GPU shape visible), so GPU models and memory
come from the docs table instead. [docs]

### 3.6 Price list

```text
GET https://apexapps.oracle.com/pls/apex/cetools/api/v1/products/?currencyCode=USD
```

668 items. [API] Item fields: `partNumber`, `displayName`, `metricName`,
`serviceCategory`, `currencyCodeLocalizations[].prices[]` with `model`
(`PAY_AS_YOU_GO`), `value`, and `rangeMin` / `rangeMax` on tiered parts.
[Documented](https://docs.oracle.com/en-us/iaas/Content/GSG/Tasks/signingup_topic-Estimating_Costs.htm)
query parameters: `partNumber`, `currencyCode`.

Prices are the same in all commercial regions: stated on Oracle's pricing pages as
found by web search, but `oracle.com/cloud/*` pages return 403 to automated clients,
so the pages themselves were not read. [unverified, strong]

Part numbers used, all present in the live list: [API]

| Series | OCPU | Memory | NVMe / GPU | USD |
| --- | --- | --- | --- | --- |
| VM / BM Standard1 (X5) | B88317 / B88315 | included | | 0.0638 |
| VM / BM Standard.B1 | B91120 / B91119 | included | | 0.0638 |
| VM / BM Standard2 (X7) | B88514 / B88513 | included | | 0.0638 |
| Standard3 (X9) | B94176 | B94177 | | 0.04 + 0.0015 |
| Standard4.Ax (X12 Ax) | B112141 | B112142 | | 0.0119 + 0.0114 |
| Standard.E2 | B90425 | included | | 0.03 |
| Standard.E3 | B92306 | B92307 | | 0.025 + 0.0015 |
| Standard.E4 | B93113 | B93114 | | 0.025 + 0.0015 |
| Standard.E5 | B97384 | B97385 | | 0.03 + 0.002 |
| Standard.E6 | B111129 | B111130 | | 0.03 + 0.002 |
| Standard.E6.Ax | B112530 | B112531 | | 0.0138 + 0.0108 |
| Standard.A1 | B93297 | B93298 | | 0.01 + 0.0015 |
| Standard.A2 | B109529 | B109530 | | 0.014 + 0.002 |
| Standard.A4 | B112145 | B112146 | | 0.0138 + 0.0027 |
| Standard.A4.Ax | B112532 | B112533 | | 0.019 + 0.0084 |
| Optimized3 (X9) | B93311 | B93312 | | 0.054 + 0.0015 |
| VM / BM DenseIO2 (X7) | B88516 / B88515 | included | | 0.1275 |
| DenseIO.E4 | B93121 | B93122 | B93123 | 0.025 + 0.0015 + 0.0612/TB |
| DenseIO.E5 | B98202 | B98203 | B98204 | 0.03 + 0.002 + 0.0612/TB |
| DenseIO.E6.Ax | B112556 | B112557 | B112558 | 0.0108 + 0.009 + 0.1433/TB |
| BM.HPC2 (X7) | B90398 | included | | 0.075 |
| VM / BM GPU2 (P100) | | | B88518 / B88517 | 1.275 / GPU |
| GPU3 (V100) | | | B89734 | 2.95 / GPU |
| GPU4 (A100 40 GB) | | | B92740 | 3.05 / GPU |
| GPU.A10 | | | B95909 | 2 / GPU |
| GPU.A100-v2 | | | B95907 | 4 / GPU |
| GPU.L40S | | | B109479 | 3.5 / GPU |
| GPU.H100 | | | B98415 | 10 / GPU |
| GPU.H200 | | | B110519 | 10 / GPU |
| GPU.B200 | | | B110978 | 14 / GPU |
| GPU.B300 | | | B112237 | 15 / GPU |
| GPU.GB200 | | | B110979 | 16 / GPU |
| GPU.GB300 | | | B112140 | 18 / GPU |
| GPU.RTXPRO | | | B112613 | 4.5 / GPU |
| GPU.MI300X | | | B109485 | 6 / GPU |
| GPU.MI355X | | | B111758 | 8.6 / GPU |

The series → part link is **our** mapping, made from the part display names. The
price list has no shape reference. The mapping of hardware generations (X5 =
Standard1, X7 = Standard2 / DenseIO2 / GPU2, X9 = Standard3 / Optimized3, X12 =
Standard4, "GPU - E3" = GPU4, "GPU Standard - V2" = GPU3) and the "GPU price includes
OCPU and memory" rule are [unverified] against the pricing page (403).

Not mapped, so listed without a price and logged:

- `BM.DenseIO.A4.Ax.72`: visible in our tenancy, no matching part. [API]
- `BM.HPC.E5.144`: part B96531 exists (0.044 / OCPU), unclear if memory is extra.
- `DenseIO1`: no part in the list.
- Parts B93544 ("GPU - E4") and B109480 ("GPU - H100T"): no shape identified.

### 3.7 Preemptible (spot)

"Preemptible capacity costs 50% less than on-demand capacity in all regions."
[docs](https://docs.oracle.com/en-us/iaas/Content/Compute/Concepts/preemptible.htm)

Supported: VM.Standard1, VM.Standard.B1, VM.Standard2, VM.Standard3.Flex,
VM.Standard.E2 (not E2.1.Micro), E3 / E4 / E5 / E6 Flex, A1.Flex, A4.Flex,
VM.DenseIO1, VM.DenseIO2, VM.GPU2, VM.GPU3, VM.Optimized3.Flex. Not available for
bare metal, burstable and extended memory instances. [docs]

### 3.8 Block Volume

From the
[performance page](https://docs.oracle.com/en-us/iaas/Content/Block/Concepts/blockvolumeperformance.htm):
[docs]

| `storage_id` | VPU/GB | IOPS/GB | Max IOPS | Max MB/s | USD/GB/month |
| --- | --- | --- | --- | --- | --- |
| `lower-cost` | 0 | 2 | 3,000 | 480 | 0.0255 |
| `balanced` | 10 | 60 | 25,000 | 480 | 0.0425 |
| `higher-performance` | 20 | 75 | 50,000 | 680 | 0.0595 |
| `ultra-high-performance` | 30 (up to 120) | 90 (up to 225) | 75,000 (up to 300,000) | 880 (up to 2,680) | 0.0765 |

Price = B91961 (storage, 0.0255) + VPUs × B91962 (0.0017). [API]

Size is 50 GB to 32 TB in 1 GB steps, from the Block Volumes FAQ as found by web
search (page not read, 403). [unverified, strong] `storage_type = NVME_SSD` is
[unverified].

### 3.9 Traffic and IPv4

Outbound parts, each free for the first 10,240 GB per month: [API]

- B88327, North America, Europe and UK: 0.0085 / GB
- B93455, APAC, Japan and South America: 0.025 / GB
- B93456, Middle East and Africa: 0.05 / GB

Region → part by the region id prefix: `us`, `ca`, `eu`, `uk` → B88327; `ap`, `sa` →
B93455; `me`, `il`, `af` → B93456. **`mx` is mapped to B88327 (North America) by
geography only.** [unverified] See §9, question 4.

IPv4: no public IP part in the price list [API], and the reserved public IP
announcement says "there is no charge to use this feature". The networking pricing
page was not read (403). [unverified, strong]

### 3.10 Compliance

HIPAA, SOC 2 Type 2 and ISO 27001 attestations, per Oracle's compliance blog posts
found by web search. The compliance page itself was not read (403).
[unverified, strong]

### 3.11 OCI Database with PostgreSQL

**API.** `list_shapes` and `list_default_configurations` work with the existing
policy. [API] `ListShapes` needs no permission ("Any authenticated user can list
shapes") [docs]; the permission of `ListDefaultConfigurations` is not documented.
`list_configurations` (custom configurations) returns `NotAuthorizedOrNotFound` and
is not needed.

`list_shapes` returns 14 entries, identical in our three regions: [API]

- 11 fixed sizes, e.g. `{'id': 'PostgreSQL.VM.Standard.E5.Flex.2.32GB', 'shape':
  'VM.Standard.E5.Flex', 'is_flexible': False, 'ocpu_count': 2,
  'memory_size_in_gbs': 32}`: E5 at 2/4/8/16/32/64 OCPUs and Standard3 at
  2/4/8/16/32 OCPUs, all with 16 GB per OCPU.
- 3 flexible shapes (`PostgreSQL.VM.Standard.E5.Flex`, `...E6.Flex`,
  `...Standard3.Flex`) with `shape_ocpu_options` (`min`, `max`) and
  `shape_memory_options` (`default_per_ocpu_in_gbs`, `min_in_gbs`, `max_in_gbs`,
  `min_per_ocpu_in_gbs`, `max_per_ocpu_in_gbs`). E6 has no fixed sizes.

`list_default_configurations` returns 136 entries, 6 of them `ACTIVE`: one per
PostgreSQL version 13 to 18, each with `shape: 'PostgreSQL'` and
`compatible_shapes: ['VM.Standard3.Flex', 'VM.Standard.E5.Flex',
'VM.Standard.E6.Flex']`. [API] The rest are `INACTIVE` older or shape-specific ones.

**Pricing model.** Two price list parts: [API]

- B99060, "Database with PostgreSQL - X86": 0.098 per OCPU hour
- B99062, "Database Optimized Storage": 0.072 per GB month

The pricing page states: "OCI Database with PostgreSQL is calculated by adding a
fee on top of your standard compute and block storage cost used to run the cluster."
[docs](https://www.oracle.com/cloud/postgresql/pricing/) (readable with a plain
download; only the fetch tool got 403). The billing docs list compute, storage,
volume performance unit cost and "related OCI Database with PostgreSQL fees".
[docs](https://docs.oracle.com/en-us/iaas/Content/postgresql/billing.htm)

The exact parts and quantities were read from the JavaScript of the
[cost estimator](https://www.oracle.com/cloud/costestimator.html) (its
`service-postgresql` module), on 2026-11-16: [estimator]

- Compute: the OCPU and memory parts of the selected compute shape × nodes.
- B99060 quantity = OCPUs × nodes.
- B99062 quantity = storage GB.
- B91962 (performance units) quantity = storage GB × VPUs of the IOPS tier.
- B91961 (Block Volume storage) quantity is set to 0, so it is **not** billed.
- IOPS → VPUs: 75K = 30, 150K = 60, … 750K = 300 (2,500 IOPS per VPU).
- Tiers of 375K IOPS and above are offered only from 16 OCPUs.
- There is no data placement option, so regional and AD-specific storage cost the
  same in the estimator.
- Default month is 744 hours.

So, as implemented:

- Node per hour = compute shape + 0.098 × OCPUs. E5 with 2 OCPUs / 32 GB:
  2 × 0.03 + 32 × 0.002 + 2 × 0.098 = 0.32.
- Storage per GB month = 0.072 + VPUs × 0.0017. At 75K IOPS: 0.123.

The first implementation also added the Block Volume storage part (0.1485 at 75K
IOPS); this was corrected after reading the estimator.

**Limits and features.** [docs]

| Fact | Value | Source |
| --- | --- | --- |
| Nodes | 1 primary + up to 7 read replicas, shared storage | manage-databases, overview |
| Failover | a read replica is promoted "within a few seconds"; RTO < 2 min, RPO 0 (multi-node) | high-availability |
| Single node | restored to a new instance; RTO < 20 min, RPO 0 | high-availability |
| Placement | regional: nodes in different ADs; AD-specific: different fault domains | high-availability |
| SLA | 99.99% multi-node, 99.9% single-node in single-AD regions | high-availability |
| Max storage | 32 TB, scales automatically, billed for used storage | manage-databases, billing |
| Performance tiers | 75K to 750K IOPS in 75K steps; 375K and above need 16+ OCPUs | performance-tiers |
| Backups | daily / weekly / monthly, automatic retention up to 35 days | overview |
| Point-in-time recovery | up to 35 days | create-db |
| Encryption | "in-transit and at rest"; own key since 2026-09-15 | overview, release notes |
| Network | private subnet only, no public endpoint | overview, create-db |
| Configurations / extensions | custom configurations, extensions enabled through them | overview |
| Monitoring | metrics, Query Insights (2026-06-16) | release notes |
| Versions | 14 to 18 in release notes; 13 also active in the API | release notes, [API] |

Not documented, so left empty: managed connection pooling, automatic minor version
upgrades, server-side TLS enforcement (the docs only show a `sslmode=verify-full`
example), IAM database authentication (only Kerberos is announced).

### 3.12 Cost estimator data (found 2026-11-16)

The [cost estimator](https://www.oracle.com/cloud/costestimator.html) is a JavaScript
app built from public JSON files under
`https://www.oracle.com/a/ocom/docs/cloudestimator2/data/`. The useful one is
`shapes.json` (93 entries): every VM, bare metal, container, dedicated host and
PostgreSQL shape with the part numbers billed for it, OCPU and memory quantities,
GPU count and memory, local disk text, and `allowPreemptible` / `allowBurstable`
flags. `products.json` holds the same prices as the price list API.

What it confirmed: [estimator]

- **Shape → part number mapping**: all 60 shapes covered by `_SHAPE_PRICE_PARTS`
  match exactly, no mismatch. This replaces the earlier "our mapping, unverified"
  status in §3.6. Two missing series were added from it: `VM.DenseIO1` (B88516) and
  `BM.HPC.E5` (B96531, OCPU only).
- **Preemptible list**: `allowPreemptible` equals `_PREEMPTIBLE_SERIES` for every
  shape.
- **Burstable**: Standard3, E3, E4 and E5 Flex only, as in the docs.
- **PostgreSQL**: the fixed E5 and Standard3 sizes bill the E5 / Standard3 compute
  parts. There are no E6 PostgreSQL entries.
- "Database Management" in the estimator is a monitoring service for Oracle
  Database (parts B93082, B93083, B93426, B96200), unrelated to PostgreSQL.

Differences worth knowing: `BM.GPU.GB200.4` is listed with 128 OCPUs and 756 GB GPU
memory here, against 144 OCPUs and 768 GB in the shapes docs.

Access: `www.oracle.com` returns 403 to the audit tool's own User-Agent (and to the
fetch tool), but 200 to plain `curl` / `requests`. `apexapps.oracle.com` and
`docs.oracle.com` accept the audit User-Agent. So `shapes.json` has to be saved by
hand and imported, like the other `www.oracle.com` pages (§9, question 14).

**Audit**: a deterministic parser (`oci_cost_estimator`) reads `shapes.json`, prices
the parts from the price list API, and emits fixed shapes as servers with prices,
flexible shapes as per-vCPU / per-GiB / local NVMe rates, and PostgreSQL shapes as
database specs and prices (1 and 2 nodes). Run against `sc-data-oci.db`: 48 server
specs and prices, 17 rate groups, 11 database specs and 33 database prices compared,
**no mismatch**; 29 `MISSING_IN_DB` findings, all GPU / HPC / Dense I/O shapes our
tenancy cannot list.

The crawler could also read `shapes.json` to list the shapes hidden from the tenancy
(§9, question 1). Not done: it has specs but no per-region availability.

---

## 4. What is implemented

### 4.1 Regions and zones

- All 44 regions are stored. Subscribed (`READY`) regions are `ACTIVE`, the rest
  `INACTIVE` with one warning. An unknown region raises (via
  `sentry_capture_or_raise`) so it gets added to the location table.
- `region_id = api_reference` = identifier, `aliases = [key]`,
  `name = display_name` = Oracle's region name ("Germany Central (Frankfurt)").
- Zones only for `ACTIVE` regions: `zone_id = {region}-ad-{n}`, and
  `name = api_reference = display_name` is the AD name **without the tenancy
  prefix** (e.g. `EU-FRANKFURT-1-AD-1`). The crawler looks up the full name for its
  own API calls (`_availability_domain`); sc-runner has to do the same with
  `list_availability_domains`.

Availability domain numbering is per tenancy [docs], so our `ad-1` is not necessarily
another tenancy's AD-1.

### 4.2 Servers

- One `list_shapes` call per `ACTIVE` zone, through `parallel_fetch_servers`.
- Fixed shapes are one server. `server_id = name = api_reference` = shape name.
- Flexible shapes are a grid, each point a separate server:
  - OCPUs: 1, 2, 4, 8, 16, 32, 64 and the shape maximum, within `ocpu_options`.
  - Memory: 2, 4 and 8 GiB **per vCPU**, skipped when outside `memory_options`.
  - `server_id = {shape}.{ocpus}-{memory_gb}`, e.g. `VM.Standard.E5.Flex.4-32`.
    `api_reference` is the `server_id` too (the shape name is not unique), and
    `api_reference_object` is
    `{"shape": ..., "shape_config": {"ocpus": ..., "memory_in_gbs": ...}}`.
  - Network: `default_per_ocpu_in_gbps × ocpus`, within min and max.
- Flexible Dense I/O shapes use the fixed configurations from the docs (8-OCPU steps,
  one 6.8 TB NVMe per 8 OCPUs). Not seen in the API, so untested against live data.
- `family`: Standard / Dense I/O / GPU / HPC / Optimized. `series`: e.g.
  `Standard.E5`, `Standard2`, `GPU.A10`.
- CPU fields from `processor_description`. `hypervisor` is left empty for the
  inspector.
- `network_speed_max` is set, baseline left empty (docs call it "max network
  bandwidth").
- Status: `ACTIVE`, except `billing_type == ALWAYS_FREE` (`VM.Standard.E2.1.Micro`) →
  `INACTIVE`.

On our tenancy this gives 288 servers from 44 shapes.

### 4.3 Prices

- On-demand: one row per `ACTIVE` zone × listed shape × configuration, Linux, USD,
  hourly. Always Free shapes and unmapped series have no price.
- A1 is priced at the paid rate; the free tier is per tenancy.
- Spot: on-demand × 0.5 for VM shapes in `_PREEMPTIBLE_SERIES`, skipping
  configurations above a NUMA node (extended memory).
- Storage, traffic and IPv4 prices are emitted for **all** regions, also the
  `INACTIVE` ones, as they do not depend on the subscription.

On our tenancy: 2,180 on-demand and 1,481 spot rows.

### 4.4 Databases

- One `list_shapes` and `list_default_configurations` call per `ACTIVE` region.
- The 11 fixed sizes are stored as is, `database_id` = the API id.
- Flexible shapes that have no fixed sizes (E6 today) are expanded to 2, 4, 8, 16,
  32 and 64 OCPUs at the default memory per OCPU, with ids in the same format (e.g.
  `PostgreSQL.VM.Standard.E6.Flex.2.32GB`). **These six ids are ours**, not Oracle's.
  Flexible shapes that do have fixed sizes are not expanded further.
- `api_reference_object` is `{"shape", "instance_ocpu_count",
  "instance_memory_size_in_gbs"}`, the arguments of `CreateDbSystem`.
- `server_id` links to the matching flex server configuration (e.g.
  `VM.Standard.E5.Flex.2-32`) when it exists. All 17 link on our tenancy.
- `engine_versions`: versions with an `ACTIVE` default configuration compatible with
  the shape.
- `ha = [MULTI_ZONE, SINGLE_ZONE, NONE]`, `ha_strategy = [READABLE_CLUSTER, NONE]`,
  `max_read_replicas = 7`, `sla = 99.99`.
- Price rows per `ACTIVE` region: single node; single-zone readable cluster (2
  nodes); multi-zone readable cluster (2 nodes), only when the region has more than
  one zone.
- Database storages: 10 performance tiers (`optimized-75k-iops` …
  `optimized-750k-iops`), `compatible_storage_ids` limited to the first four below
  16 OCPUs. Storage prices only in `ACTIVE` regions where the service lists shapes.

On our tenancy: 17 databases, 153 database prices, 10 storages, 30 storage prices.

### 4.5 Not implemented

- Burstable variants.
- Windows and other licensed images.
- `founding_year` / `green_energy` of regions.

---

## 5. Files changed

- `src/sc_crawler/vendors/vendors.py`, `__init__.py`: the `oci` vendor.
- `src/sc_crawler/vendors/_oci.py`: the module.
- `pyproject.toml`: `oci = ["oci"]`, added to `vendors`.
- `src/sc_crawler/inspector.py`: `"oci": True` in
  `_boot_from_attached_network_drive`. **Assumption**: OCI instances boot from a
  network boot volume. Must match the sc-runner resource once written.
- `docs/index.md`: credentials section.
- `docs/add_vendor.md`: template uses the current `network_speed_*` fields.
- `tests/test_oci.py`: 74 tests, skipped when the `oci` SDK is not installed.
- `src/sc_crawler/lookup.py`: `MA` and `CO` countries.
- `audit/sources.yaml`: `oci` block.
- `CHANGELOG.md`: development section.

Not done here:

- `.claude/settings.json`: `WebFetch(domain:oracle.com)` for the audit skill. The
  edit was blocked by the permission classifier, so add it by hand if wanted.
- Outside this repo: logo, sc-runner Pulumi resource, sc-inspector support,
  `resource-tracker` cloud discovery.

---

## 6. Next phases

1. **Spot-check one database configuration** in the cost estimator UI (§9,
   question 9); the model itself is confirmed from the estimator's code.
2. **Tenancy setup**: subscribe to the other regions, and request limits for GPU,
   HPC and VM Dense I/O shapes (or decide on question 1).
3. **Check GPU and VM Dense I/O data** once those shapes are visible:
   `gpu_description` values, Dense I/O flex options, and the GPU price mapping.
4. **Burstable variants** (optional).
5. **Audit** with the `vendor-audit` skill. The `oracle.com` pricing pages block
   automated clients, so they need a browser export.

---

## 7. Tests

`tests/test_oci.py` mocks `_get_shapes`, `_get_price_list`, `_get_regions`,
`_get_region_subscriptions` and `_get_availability_domains` with plain dicts shaped
like the live responses. Covered: config from env vars and file, zone id
normalization, shape series and family, processor parsing for all eight live strings,
OCPU → vCPU, flex grid and limits, Dense I/O flex, GPU fields, status, price formulas,
unknown series, spot eligibility, storage, traffic tiers, IPv4.

The database tests mock `_get_database_shapes` and
`_get_database_default_configurations` the same way, and cover the fixed and expanded
sizes, versions, storage tier limits, the three HA price rows, single-AD regions and
storage prices.

The `oci` SDK is now in `.venv`, which has an editable install, so
`.venv/bin/python -m pytest tests/test_oci.py` is enough.

---

## 8. Risks

- **Tenancy-specific data.** Regions, zones, shapes and AD names all depend on the
  crawler's tenancy. A change of credentials changes the dataset.
- **Price mapping drift.** New shape series need a new entry in `_SHAPE_PRICE_PARTS`.
  They are logged once and listed without a price, not failed.
- **GPU path is untested on live data.**
- **Flex grid size.** 12 flex shapes produce about 250 servers. With all 44 regions
  subscribed, that is roughly 15,000 on-demand price rows.
- **Uniform pricing.** The price list cannot express regional differences.
- **Database prices follow the cost estimator's code**, not a bill (§3.11).

---

## 9. Open questions

1. **Shapes hidden by service limits.** Request limits for every shape family in the
   crawler tenancy (recommended, keeps the data API-driven), or add a docs-based
   fallback list for GPU / HPC / Dense I/O shapes?
2. **Region subscriptions.** Subscribe the tenancy to all 44 regions? Until then 41
   regions are `INACTIVE` with storage, traffic and IPv4 prices but no servers. Should
   those regions be hidden instead?
3. **Flex grid.** Is 2 / 4 / 8 GiB per vCPU with power-of-two OCPUs the right grid?
   The shape defaults differ (E5: 12 GB per OCPU, E4: 16, A1: 6), and the grid drives
   sc-inspector cost. Is the `VM.Standard.E5.Flex.4-32` id format fine for sc-runner?
4. **Mexico egress group.** Is `mx-*` billed as North America (0.0085) or with South
   America (0.025)? Needs the networking pricing page or a bill.
5. **Ultra High Performance volumes.** Listed once at the 30 VPU minimum. List the
   120 VPU maximum as well?
6. **Always Free micro shape.** `INACTIVE` without a price now. Alternative: `ACTIVE`
   at price 0.
7. ~~Tenancy prefix in `Zone.api_reference`.~~ Decided: not stored.
8. **Unpriced shapes.** Keep them `ACTIVE` without prices, or mark `INACTIVE`?
9. ~~Database pricing model.~~ Resolved from the cost estimator's code, see §3.11.
   Still worth one manual check in the estimator UI (E5, 2 OCPUs / 32 GB, 1 node,
   100 GB at 75K IOPS: 238.08 compute + 12.30 storage per 744-hour month).
10. ~~VPUs above 300,000 IOPS.~~ Resolved: the estimator uses 30 VPUs per 75K IOPS up
    to 300 VPUs.
11. ~~Regional storage.~~ The estimator has no placement option, so one price.
12. **E6 database sizes.** Six sizes are generated for the flex-only E6 shape. Keep,
    or store only Oracle's fixed sizes (E5 and Standard3)?
13. **HA price rows.** Readable clusters are priced with 2 nodes (primary + 1
    replica). Up to 8 nodes are possible.
14. **Audit access to `www.oracle.com`.** The site rejects the audit's User-Agent.
    Keep importing by hand (`sc-audit import-page oci cost-estimator-shapes FILE`),
    or change how the audit identifies itself for this host?
