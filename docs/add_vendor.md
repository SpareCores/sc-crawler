# Vendor support

Each file in the [`src/sc_crawler/vendors`](https://github.com/SpareCores/sc-crawler/tree/main/src/sc_crawler/vendors) folder provides the required helpers for a given [Vendor][sc_crawler.tables.Vendor], named as the `id` of the vendor prefixed with an underscore. For example, [`_aws.py`](https://github.com/SpareCores/sc-crawler/tree/main/src/sc_crawler/vendors/_aws.py) provides functions to be used by its [Vendor][sc_crawler.tables.Vendor] instance, called [`aws`][sc_crawler.vendors.aws].

## First steps

1. Define the new [Vendor][sc_crawler.tables.Vendor] instance in `src/sc_crawler/vendors/vendors.py`.
2. Copy the below [template file](#template-file-for-new-vendors) as a starting point to `src/sc_crawler/vendors/_<vendor_id>.py`.
3. Update `src/sc_crawler/vendors/__init__.py` to include the new vendor.
4. If the vendor's SDK is needed, add it as an optional dependency named after the vendor id in `pyproject.toml`, and list that in the `vendors` extra.
5. Update the "Collect data" section of `docs/index.md` with the credential and permission requirements for the new vendor.
6. Implement the `inventory` methods.
7. Make sure that the country of the vendor and of all its regions is listed in `country_continent_mapping` in `src/sc_crawler/lookup.py`, as the related `Country` rows are created from that.
8. Add unit tests in `tests/test_<vendor_id>.py` with mocked API responses.
9. Add the official pages to cross-check the collected data to `audit/sources.yaml`, and describe the new vendor in `CHANGELOG.md`.
10. Preferably also implement the related cloud-discovery tool in the `resource-tracker` package.
11. Add the new vendor to `_boot_from_attached_network_drive` in `_find_storage_disks_from_lsblk` ([`src/sc_crawler/inspector.py`](https://github.com/SpareCores/sc-crawler/blob/main/src/sc_crawler/inspector.py)). The value (`True` or `False`) must match whether the vendor's Pulumi provisioning script in the [sc-runner](https://github.com/SpareCores/sc-runner) repo attaches a network block volume as the boot drive: check `src/sc_runner/resources/<vendor_id>.py`.

## Inventory methods

Each vendor module should provide the below functions:

- `inventory_compliance_frameworks`: Define [`VendorComplianceLink`][sc_crawler.tables.VendorComplianceLink] instances to describe which frameworks the vendor complies with. Optionally include references in the `comment` field. To avoid duplicating [`ComplianceFramework`][sc_crawler.tables.ComplianceFramework] instances, easiest is to use the `compliance_framework_id` field instead of the `compliance_framework` relationship, preferably via [sc_crawler.lookup.map_compliance_frameworks_to_vendor][].
- `inventory_regions`: Define [`Region`][sc_crawler.tables.Region] instances with location, energy source etc for each region the vendor has.
- `inventory_zones`: Define a [`Zone`][sc_crawler.tables.Zone] instance for each availability zone of the vendor in each region.
- `inventory_servers`: Define [`Server`][sc_crawler.tables.Server] instances for the vendor's server/instance types.
- `inventory_server_prices`: Define the [`ServerPrice`][sc_crawler.tables.ServerPrice] instances for the standard/ondemand (or optionally also for the reserved) pricing of the instance types per region and zone. When applicable, include the monthly cap for tiered pricing in the `price_tiered` field.
- `inventory_server_prices_spot`: Similar to the above, define [`ServerPrice`][sc_crawler.tables.ServerPrice] instances but the `allocation` field set to [`Allocation.SPOT`][sc_crawler.table_fields.Allocation]. Very likely to see different spot prices per region/zone.
- `inventory_storages`: Define [`Storage`][sc_crawler.tables.Storage] instances to describe the available storage options that can be attached to the servers.
- `inventory_storage_prices`: Define [`StoragePrice`][sc_crawler.tables.StoragePrice] instances for the pricing of the storage options per region.
- `inventory_databases`: Define [`Database`][sc_crawler.tables.Database] instances for managed database instances (e.g. PostgreSQL).
- `inventory_database_prices`: Define [`DatabasePrice`][sc_crawler.tables.DatabasePrice] instances for compute pricing per region. `ha` and `ha_strategy` are scalar primary-key fields (one price row per HA deployment). Use hourly `price` with optional monthly cap in `price_tiered`.
- `inventory_database_storages`: Define [`DatabaseStorage`][sc_crawler.tables.DatabaseStorage] instances for decoupled or add-on storage products.
- `inventory_database_storage_prices`: Define [`DatabaseStoragePrice`][sc_crawler.tables.DatabaseStoragePrice] instances for storage pricing per region.
- `inventory_traffic_prices`: Define [`TrafficPrice`][sc_crawler.tables.TrafficPrice] instances to describe the pricing of ingress/egress traffic.
- `inventory_ipv4_prices`: Define [`Ipv4Price`][sc_crawler.tables.Ipv4Price] instances on the price of an IPv4 address.

Each function will be picked up as the related [Vendor][sc_crawler.tables.Vendor] instance's instance methods, so each
function should take a single argument, that is the [Vendor][sc_crawler.tables.Vendor] instance.
E.g. [sc_crawler.vendors._aws.inventory_regions][] is called by [sc_crawler.tables.Vendor.inventory_regions][].

The functions should return an array of dict representing the related objects. The vendor's `inventory` method will pass the array to [sc_crawler.insert.insert_items][] along with the table object.

Other functions and variables must be prefixed with an underscore to suggest those are internal tools.

## Hypervisor

Set `hypervisor` on every `Server` row to a [Hypervisor][sc_crawler.table_fields.Hypervisor] value, and use `BARE_METAL` for servers without a hypervisor. Prefer an API field (e.g. AWS's `BareMetal` and `Hypervisor`), otherwise a documented naming rule (e.g. the `-metal` suffix at GCP or the `BM.` prefix at OCI), with the source URL in a comment. Leave it empty only when the hypervisor is not known, as an empty value does not mean bare metal. The `Hypervisor vendor` reported by `lscpu` can confirm the vendor's information, but it is not reliable on its own: e.g. KVM with Hyper-V enlightenments reports Microsoft, and ARM servers report no hypervisor.

## Status and retirement checks

Set `status` on every `Server` and `Database` row. Possible values: `ACTIVE`, `INACTIVE`, `PLANNED_FOR_RETIREMENT`, `RETIRED`. See [Status][sc_crawler.table_fields.Status] for the definition of each.

- Map the vendor's lifecycle API fields to these four states. Document the mapping in the `inventory_servers` / `inventory_databases` docstring.
- Use only explicit API or documentation signals for `PLANNED_FOR_RETIREMENT` and `RETIRED`. Do not infer retirement from naming patterns like "previous generation" unless there is a confirmed mapping.
- If multiple signals exist (e.g. per-region availability), pick the best: `ACTIVE` > `PLANNED_FOR_RETIREMENT` > `INACTIVE` > `RETIRED`.
- Set `retirement_date` on the `PLANNED_FOR_RETIREMENT` and `RETIRED` rows when the vendor publishes a retirement date: the end of support (shutdown) if published, otherwise the end of sale or orderability (take the latest one when dates are published per region), and leave it empty otherwise. Prefer an API field (e.g. Hetzner's `deprecation.unavailable_after`). When the date is only in the docs, list it in a `_<VENDOR>_RETIREMENT_RULES` tuple of `(compiled regex on the SKU name, date)` pairs with the source URL of each, matched by [retirement_date_from_rules][sc_crawler.vendor_helpers.retirement_date_from_rules]. If the date is the only lifecycle signal (e.g. Azure), derive `status` from it with [status_from_retirement_date][sc_crawler.vendor_helpers.status_from_retirement_date]. SKUs no longer returned by the vendor keep their stored status and date, as these are not set to `INACTIVE` by `pull`.
- The `status` of the other records is optional (defaults to `ACTIVE`), and can be set when needed: e.g. `INACTIVE` for a region that is listed by the vendor but cannot be queried with the credentials (like the regions an Oracle Cloud Infrastructure tenancy is not subscribed to), or for the price of a server that is sold out in a region.
- Never set `ARCHIVED` in a vendor module. It is not a vendor signal: it marks records that we replaced by another record (e.g. after changing how the ids of a vendor's regions are generated) or dropped on purpose, and it is set only from the rules in [sc_crawler.archive_rules][]. When changing the id of existing records, add a rule there for each old → new pair instead of leaving the old records behind as `INACTIVE`.

## Progress bars

To create progress bars, you can use the [Vendor][sc_crawler.tables.Vendor]'s [progress_tracker][sc_crawler.tables.Vendor.progress_tracker] attribute with the below methods:

* [start_task][sc_crawler.logger.VendorProgressTracker.start_task]
* [advance_task][sc_crawler.logger.VendorProgressTracker.advance_task]
* [hide_task][sc_crawler.logger.VendorProgressTracker.hide_task]

The [start_task][sc_crawler.logger.VendorProgressTracker.start_task] will register a task in the "Current tasks"
progress bar list with the provided name automatically prefixed by the vendor name, and the provided number of expected
steps. You should call [advance_task][sc_crawler.logger.VendorProgressTracker.advance_task] after each step finished,
which will by default update the most recently created task's progress bar. If making updates in parallel, store the
`TaskID` returned by [start_task][sc_crawler.logger.VendorProgressTracker.start_task] and pass
to [advance_task][sc_crawler.logger.VendorProgressTracker.advance_task]
and [hide_task][sc_crawler.logger.VendorProgressTracker.hide_task] explicitly. Make sure to call `hide_task` when the
progress bar is not to be shown anymore. It's a good practice to log the number of fetched/synced objects afterwards
with `logger.info`. See the manual of [`VendorProgressTracker`][sc_crawler.logger.VendorProgressTracker] for more
details.

Basic example:

```python
def inventory_zones(vendor):
    zones = range(5)
    vendor.progress_tracker.start_task(name="Searching zones", total=len(zones))
    for zone in zones:
        # do something
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return zones
```

## Template file for new vendors

```python
def inventory_compliance_frameworks(vendor):
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id,
        [
            #    "hipaa",
            #    "soc2t2",
            #    "iso27001",
        ],
    )


def inventory_regions(vendor):
    items = []
    # for region in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "region_id": "",
    #             "name": "",
    #             "api_reference": "",
    #             "display_name": "",
    #             "aliases": [],
    #             "country_id": "",
    #             "state": None,
    #             "city": None,
    #             "address_line": None,
    #             "zip_code": None,
    #             "lon": None,
    #             "lat": None,
    #             "founding_year": None,
    #             "green_energy": None,
    #         }
    #     )
    return items


def inventory_zones(vendor):
    items = []
    # for zone in []:
    #     items.append({
    #         "vendor_id": vendor.vendor_id,
    #         "region_id": "",
    #         "zone_id": "",
    #         "name": "",
    #         "api_reference": "",
    #         "display_name": "",
    #     })
    return items


def inventory_servers(vendor):
    items = []
    # for server in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "server_id": ,
    #             "name": ,
    #             "api_reference": ,
    #             "api_reference_object": None,
    #             "display_name": ,
    #             "description": None,
    #             "family": None,
    #             "series": None,
    #             "vcpus": ,
    #             "hypervisor": Hypervisor....,
    #             "cpu_allocation": CpuAllocation....,
    #             "cpu_cores": None,
    #             "cpu_speed": None,
    #             "cpu_architecture": CpuArchitecture....,
    #             "cpu_manufacturer": None,
    #             "cpu_family": None,
    #             "cpu_model": None,
    #             "cpu_l1d_cache": None,
    #             "cpu_l1d_cache_total": None,
    #             "cpu_l1i_cache": None,
    #             "cpu_l1i_cache_total": None,
    #             "cpu_l2_cache": None,
    #             "cpu_l2_cache_total": None,
    #             "cpu_l3_cache": None,
    #             "cpu_l3_cache_total": None,
    #             "cpu_flags": [],
    #             "cpus": [],
    #             "memory_amount": ,
    #             "memory_generation": None,
    #             "memory_speed": None,
    #             "memory_ecc": None,
    #             "accelerator_count": 0,
    #             "accelerator_memory_min": None,
    #             "accelerator_memory_total": None,
    #             "accelerator_type": None,
    #             "accelerator_manufacturer": None,
    #             "accelerator_family": None,
    #             "accelerator_model": None,
    #             "accelerators": [],
    #             "storage_size": 0,
    #             "storage_type": None,
    #             "storages": [],
    #             "storage_read_iops_max": None,
    #             "storage_write_iops_max": None,
    #             "storage_read_throughput_max": None,  # MB/s
    #             "storage_write_throughput_max": None,  # MB/s
    #             "compatible_storage_ids": None,  # [] if none can be attached
    #             "network_speed_baseline": None,  # Gbps
    #             "network_speed_max": None,  # Gbps
    #             "network_storage_speed_baseline": None,  # Gbps
    #             "network_storage_speed_max": None,  # Gbps
    #             "inbound_traffic": 0,
    #             "outbound_traffic": 0,
    #             "ipv4": 0,
    #             "status": Status.ACTIVE,
    #         }
    #     )
    return items


def inventory_server_prices(vendor):
    items = []
    # for server in []:
    #     items.append({
    #         "vendor_id": ,
    #         "region_id": ,
    #         "zone_id": ,
    #         "server_id": ,
    #         "operating_system": ,
    #         "allocation": Allocation....,
    #         "unit": PriceUnit.HOUR,
    #         "price": ,
    #         "price_upfront": 0,
    #         "price_tiered": [
    #             {"lower": 0, "upper": monthly_cap, "price": hourly_price},
    #             {"lower": monthly_cap + 1, "upper": "Infinity", "price": 0},
    #         ],
    #         "currency": "USD",
    #     })
    return items


def inventory_server_prices_spot(vendor):
    return []


def inventory_storages(vendor):
    items = []
    # for storage in []:
    #     items.append(
    #         {
    #             "storage_id": ,
    #             "vendor_id": vendor.vendor_id,
    #             "name": ,
    #             "description": None,
    #             "storage_type": StorageType....,
    #             "max_iops": None,
    #             "max_throughput": None,
    #             "min_size": None,
    #             "max_size": None,
    #         }
    #     )
    return items


def inventory_storage_prices(vendor):
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "region_id": ,
    #             "storage_id": ,
    #             "unit": PriceUnit.GB_MONTH,
    #             "price": ,
    #             "currency": "USD",
    #         }
    #     )
    return items


def inventory_traffic_prices(vendor):
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "region_id": ,
    #             "price": ,
    #             "price_tiered": [],
    #             "currency": "USD",
    #             "unit": PriceUnit.GB_MONTH,
    #             "direction": TrafficDirection....,
    #         }
    #     )
    return items


def inventory_ipv4_prices(vendor):
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "region_id": ,
    #             "price": ,
    #             "currency": "USD",
    #             "unit": PriceUnit.MONTH,
    #         }
    #     )
    return items


def inventory_databases(vendor):
    items = []
    # for database in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "database_id": ,
    #             "name": ,
    #             "api_reference": ,
    #             # Named API args for provisioning (e.g. Pulumi/Terraform).
    #             "api_reference_object": None,
    #             "display_name": ,
    #             "description": None,
    #             "family": None,
    #             "series": None,
    #             "server_id": None,
    #             "vcpus": None,
    #             "memory_amount": None,  # MiB
    #             "engine": DatabaseEngine.POSTGRESQL,
    #             "wire_protocol": DatabaseWireProtocol.POSTGRESQL,
    #             "engine_versions": ["16", "17"],
    #             "auto_upgrade_versions": None,
    #             # Ordered JSON lists (highest tier first); defaults to [NONE].
    #             "ha": [DatabaseHaLevel.NONE],
    #             "ha_strategy": [DatabaseHaStrategy.NONE],
    #             "max_read_replicas": None,
    #             "custom_config": None,
    #             "custom_extensions": None,
    #             "storage_size": None,  # bundled GB
    #             "storage_extra_min": None,  # GB
    #             "storage_extra_max": None,  # GB
    #             "storage_extra_autosize": None,
    #             "compatible_storage_ids": None,  # [] if none can be attached
    #             "disk_encryption": None,
    #             "scheduled_backups": None,
    #             "continuous_backups": None,  # max PITR retention (days)
    #             "connection_pool": None,
    #             "system_monitoring": None,
    #             "database_monitoring": None,
    #             "autotuning_advice": None,
    #             "autotuning_apply": None,
    #             "sla": None,  # e.g. 99.95
    #             # Supported security capabilities for this db instance.
    #             "security_features": [
    #                 # DatabaseSecurityFeature.IP_FILTERING,
    #                 # DatabaseSecurityFeature.PRIVATE_NETWORK,
    #                 # DatabaseSecurityFeature.NETWORK_PEERING,
    #                 # DatabaseSecurityFeature.IDENTITY_BASED_AUTH,
    #                 # DatabaseSecurityFeature.CLIENT_CERT_AUTH,
    #                 # DatabaseSecurityFeature.ENFORCED_TLS,
    #                 # DatabaseSecurityFeature.CUSTOMER_MANAGED_KEYS,
    #                 # DatabaseSecurityFeature.AUDIT_LOGGING,
    #             ],
    #             "status": Status.ACTIVE,
    #         }
    #     )
    return items


def inventory_database_prices(vendor):
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "region_id": ,
    #             "database_id": ,
    #             "allocation": Allocation.ONDEMAND,
    #             # Scalar PK fields: one row per HA deployment (e.g. Single-AZ vs Multi-AZ).
    #             "ha": DatabaseHaLevel.NONE,
    #             "ha_strategy": DatabaseHaStrategy.NONE,
    #             "unit": PriceUnit.HOUR,
    #             "price": ,
    #             "price_upfront": 0,
    #             "price_tiered": [],
    #             "currency": "USD",
    #         }
    #     )
    return items


def inventory_database_storages(vendor):
    items = []
    # for storage in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "database_storage_id": ,
    #             "name": ,
    #             "description": None,
    #             "scope": DatabaseStorageScope.DATA,
    #             "redundancy": None,
    #             "min_size": None,
    #             "max_size": None,
    #             "max_iops": None,
    #             "max_throughput": None,
    #         }
    #     )
    return items


def inventory_database_storage_prices(vendor):
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "region_id": ,
    #             "database_storage_id": ,
    #             "unit": PriceUnit.GB_MONTH,
    #             "price": ,
    #             "currency": "USD",
    #         }
    #     )
    return items
```
