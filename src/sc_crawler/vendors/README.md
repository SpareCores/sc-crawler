# Vendor-specific crawler tools

Each file in this folder provides the required helpers for a given vendor, named as the identifier of the vendor.
For example, `aws.py` provides functions to be used by its `Vendor` instance, called `aws`.

## Inventory methods

Each file should provide the below functions:

- `inventory_compliance_frameworks`: Define `VendorComplianceLink` instances to describe which frameworks the vendor complies with. Optionally include references in the `comment` field. To avoid duplicating `ComplianceFramework` instances, easiest is to use the `compliance_framework_id` field instead of the `compliance_framework` relationship.
- `inventory_datacenters`: Define `Datacenter` instances with location, energy source etc for each region/datacenter the vendor has.
- `inventory_zones`: Define a `Zone` instance for each availability zone of the vendor in each datacenter.
- `inventory_servers`: Define `Server` instances for the vendor's server/instance types.
- `inventory_server_prices`: Define the `ServerPrice` instances for the standard/ondemand (or optionally also for the reserved) pricing of the instance types per datacenter and zone.
- `inventory_server_prices_spot`: Similar to the above, define `ServerPrice` instances but the `allocation` field set to `Allocation.SPOT`. Very likely to see different spot prices per datacenter/zone.
- `inventory_storage_prices`: Define `StoragePrice` instances to describe the available storage options that can be attached to the servers.
- `inventory_traffic_prices`: Define `TrafficPrice` instances to describe the pricing of ingress/egress traffic.
- `inventory_ipv4_prices`: Define `Ipv4Price` instances on the price of an IPv4 address.

Each function will be picked up as the related `Vendor` instance's instance methods, so each function should take a single argument, that is the `Vendor` instance. No need to return the objects -- it's enough to define the above-mentioned instances.

If a helper is not needed (e.g. another helper already provides its output, or there are no spot prices), it is still required, but can return early, e.g. if `Zone` objects were populated by `inventory_datacenters` already, do something like:

```python
def inventory_zones(self):
    """Zones were already provided in inventory_datacenters."""
    pass
```

Other functions and variables must be prefixed with an underscore to suggest those are internal tools.

## Progress bars

To create progress bars, you can use the `Vendor`'s `progress_tracker` attribute with the below methods:

* `start_task`
* `advance_task`
* `hide_task`

The `start_task` will register a task in the "Current tasks" progress bar list with the provided name automatically prefixed by the vendor name, and the provided number of expected steps. You should call `advance_task` after each step finished, which will by default update the most recently created task's progress bar. If making updates in parallel, store the `TaskID` returned by `start_task` and pass to `advance_task` and `hide_task` explicitly. Make sure to call `hide_task` when the progress bar is not to be shown anymore. It's a good practice to log the number of fetched/synced objects afterwards with `logger.info.` See the manual of `VendorProgressTracker` for more details.

## Template file for new vendors

```python
from ..schemas import (
    VendorComplianceLink,
    Datacenter,
    Disk,
    Duration,
    Gpu,
    Ipv4Price,
    Server,
    ServerPrice,
    Zone,
)


def inventory_compliance_frameworks(vendor):
    pass


def inventory_datacenters(vendor):
    pass


def inventory_zones(vendor):
    pass


def inventory_servers(vendor):
    pass


def inventory_server_prices(vendor):
    pass


def inventory_server_prices_spot(vendor):
    pass


def inventory_storage_prices(vendor):
    pass


def inventory_traffic_prices(vendor):
    pass


def inventory_ipv4_prices(vendor):
    pass
```
