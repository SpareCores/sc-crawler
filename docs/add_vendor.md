# Vendor support

Each file in the [`src/sc_crawler/vendors`](https://github.com/SpareCores/sc-crawler/tree/main/src/sc_crawler/vendors) folder provides the required helpers for a given [Vendor][sc_crawler.tables.Vendor], named as the `id` of the vendor. For example, [`aws.py`](https://github.com/SpareCores/sc-crawler/tree/main/src/sc_crawler/vendors/aws.py) provides functions to be used by its [Vendor][sc_crawler.tables.Vendor] instance, called [`aws`][sc_crawler.vendors.aws].

## First steps

1. Define the new [Vendor][sc_crawler.tables.Vendor] instance in `src/sc_crawler/vendors/vendors.py`.
2. Copy the below [template file](#template-file-for-new-vendors) as a starting point to `src/sc_crawler/vendors/{vendor_id}.py`.
3. Update `src/sc_crawler/vendors/__init__.py` to include the new vendor.
4. Update `docs/add_vendor.md` with the credential requirements for the new vendor.
5. Implement the `inventory` methods.

## Inventory methods

Each vendor module should provide the below functions:

- `inventory_compliance_frameworks`: Define [`VendorComplianceLink`][sc_crawler.tables.VendorComplianceLink] instances to describe which frameworks the vendor complies with. Optionally include references in the `comment` field. To avoid duplicating [`ComplianceFramework`][sc_crawler.tables.ComplianceFramework] instances, easiest is to use the `compliance_framework_id` field instead of the `compliance_framework` relationship, preferably via [sc_crawler.lookup.map_compliance_frameworks_to_vendor][].
- `inventory_datacenters`: Define [`Datacenter`][sc_crawler.tables.Datacenter] instances with location, energy source etc for each region/datacenter the vendor has.
- `inventory_zones`: Define a [`Zone`][sc_crawler.tables.Zone] instance for each availability zone of the vendor in each datacenter.
- `inventory_servers`: Define [`Server`][sc_crawler.tables.Server] instances for the vendor's server/instance types.
- `inventory_server_prices`: Define the [`ServerPrice`][sc_crawler.tables.ServerPrice] instances for the standard/ondemand (or optionally also for the reserved) pricing of the instance types per datacenter and zone.
- `inventory_server_prices_spot`: Similar to the above, define [`ServerPrice`][sc_crawler.tables.ServerPrice] instances but the `allocation` field set to [`Allocation.SPOT`][sc_crawler.table_fields.Allocation]. Very likely to see different spot prices per datacenter/zone.
- `inventory_storage_prices`: Define [`StoragePrice`][sc_crawler.tables.StoragePrice] instances to describe the available storage options that can be attached to the servers.
- `inventory_traffic_prices`: Define [`TrafficPrice`][sc_crawler.tables.TrafficPrice] instances to describe the pricing of ingress/egress traffic.
- `inventory_ipv4_prices`: Define [`Ipv4Price`][sc_crawler.tables.Ipv4Price] instances on the price of an IPv4 address.

Each function will be picked up as the related [Vendor][sc_crawler.tables.Vendor] instance's instance methods, so each function should take a single argument, that is the [Vendor][sc_crawler.tables.Vendor] instance. E.g. [sc_crawler.vendors.aws.inventory_datacenters][] is called by [sc_crawler.tables.Vendor.inventory_datacenters][].

The functions should return an array of dict representing the related objects. The vendor's `inventory` method will pass the array to [sc_crawler.insert.insert_items][] along with the table object.

Other functions and variables must be prefixed with an underscore to suggest those are internal tools.

## Progress bars

To create progress bars, you can use the [Vendor][sc_crawler.tables.Vendor]'s [progress_tracker][sc_crawler.tables.Vendor.progress_tracker] attribute with the below methods:

* [start_task][sc_crawler.logger.VendorProgressTracker.start_task]
* [advance_task][sc_crawler.logger.VendorProgressTracker.advance_task]
* [hide_task][sc_crawler.logger.VendorProgressTracker.hide_task]

The [start_task][sc_crawler.logger.VendorProgressTracker.start_task] will register a task in the "Current tasks" progress bar list with the provided name automatically prefixed by the vendor name, and the provided number of expected steps. You should call [advance_task][sc_crawler.logger.VendorProgressTracker.advance_task] after each step finished, which will by default update the most recently created task's progress bar. If making updates in parallel, store the [rich.progress.TaskID][] returned by [start_task][sc_crawler.logger.VendorProgressTracker.start_task] and pass to [advance_task][sc_crawler.logger.VendorProgressTracker.advance_task] and [hide_task][sc_crawler.logger.VendorProgressTracker.hide_task] explicitly. Make sure to call `hide_task` when the progress bar is not to be shown anymore. It's a good practice to log the number of fetched/synced objects afterwards with `logger.info.` See the manual of [`VendorProgressTracker`][sc_crawler.logger.VendorProgressTracker] for more details.

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
    return map_compliance_frameworks_to_vendor(vendor.vendor_id, [
    #    "hipaa",
    #    "soc2t2",
    #    "iso27001",
    ])


def inventory_datacenters(vendor):
    items = []
    # for datacenter in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "datacenter_id": "",
    #             "name": "",
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
    items =[]
    # for zone in []:
    #     items.append({
    #         "vendor_id": vendor.vendor_id,
    #         "datacenter_id": "",
    #         "zone_id": "",
    #         "name": "",
    #     })
    return items


def inventory_servers(vendor):
    # items = []
    # for server in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "server_id": ,
    #             "name": ,
    #             "description": None,
    #             "vcpus": ,
    #             "hypervisor": None,
    #             "cpu_allocation": CpuAllocation....,
    #             "cpu_cores": None,
    #             "cpu_speed": None,
    #             "cpu_architecture": CpuArchitecture....,
    #             "cpu_manufacturer": None,
    #             "cpu_family": None,
    #             "cpu_model": None,
    #             "cpus": [],
    #             "memory": ,
    #             "gpu_count": 0,
    #             "gpu_memory_min": None,
    #             "gpu_memory_total": None,
    #             "gpu_manufacturer": None,
    #             "gpu_model": None,
    #             "gpus": [],
    #             "storage_size": 0,
    #             "storage_type": None,
    #             "storages": [],
    #             "network_speed": None,
    #             "inbound_traffic": 0,
    #             "outbound_traffic": 0,
    #             "ipv4": 0,
    #         }
    #     )
    # return items


def inventory_server_prices(vendor):
    # items = []
    # for server in []:
    #     items.append({
    #         "vendor_id": ,
    #         "datacenter_id": ,
    #         "zone_id": ,
    #         "server_id": ,
    #         "operating_system": ,
    #         "allocation": Allocation....,
    #         "unit": "hourly",
    #         "price": ,
    #         "price_upfront": 0,
    #         "price_tiered": [],
    #         "currency": "USD",
    #     })
    # return items


def inventory_server_prices_spot(vendor):
    return []


def inventory_storage(vendor):
    # items = []
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
    # return items


def inventory_storage_prices(vendor):
    # items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "datacenter_id": ,
    #             "storage_id": ,
    #             "unit": PriceUnit.GB_MONTH,
    #             "price": ,
    #             "currency": "USD",
    #         }
    #     )
    # return items


def inventory_traffic_prices(vendor):
    # items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "datacenter_id": ,
    #             "price": ,
    #             "price_tiered": [],
    #             "currency": "USD",
    #             "unit": PriceUnit.GB_MONTH,
    #             "direction": TrafficDirection....,
    #         }
    #     )
    # return items


def inventory_ipv4_prices(vendor):
    # items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "datacenter_id": ,
    #             "price": ,
    #             "currency": "USD",
    #             "unit": PriceUnit.HOUR,
    #         }
    #     )
    # return items
```
