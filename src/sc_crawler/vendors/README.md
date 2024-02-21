## Vendor-specific crawler tools

Each file in this folder provides the required helpers for a given vendor, named as the identifier of the vendor.
For example, `aws.py` provides functions to be used by its `Vendor` instance, called `aws`.

Each file should provide the below functions:

- `get_compliance_frameworks`: Define `VendorComplianceLink` instances to describe which frameworks the vendor complies with. Optionally include references in the `comment` field. To avoid duplicating `ComplianceFramework` instances, easiest is to use the `compliance_framework_id` field instead of the `compliance_framework` relationship.
- `get_datacenters`: Define `Datacenter` instances with location, energy source etc for each region/datacenter the vendor has.
- `get_zones`: Define a `Zone` instance for each availability zone of the vendor in each datacenter.
- `get_servers`: Define `Server` instances for the vendor's server/instance types.
- `get_server_prices`: Define the `ServerPrice` instances for the standard/ondemand (or optionally also for the reserved) pricing of the instance types per datacenter and zone.
- `get_server_prices_spot`: Similar to the above, define `ServerPrice` instances but the `allocation` field set to `Allocation.SPOT`. Very likely to see different spot prices per datacenter/zone.
- `get_storage_prices`: Define `StoragePrice` instances to describe the available storage options that can be attached to the servers.
- `get_traffic_prices`: Define `TrafficPrice` instances to describe the pricing of ingress/egress traffic.
- `get_ipv4_prices`: Define `Ipv4Price` instances on the price of an IPv4 address.

Each function will be picked up as the related `Vendor` instance's instance methods, so each function should take a single argument, that is the `Vendor` instance. No need to return the objects -- it's enough to define the above-mentioned instances.

If a helper is not needed (e.g. another helper already provides its output, or there are no spot prices), it is still required, but can return early, e.g. if `Zone` objects were populated by `get_datacenters` already, do something like:

```python
def get_zones(self):
    """Zones were already provided in get_datacenters."""
    pass
```

Other functions and variables must be prefixed with an underscore to suggest those are internal tools.

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


def get_compliance_frameworks(vendor):
    pass


def get_datacenters(vendor):
    pass


def get_zones(vendor):
    pass


def get_servers(vendor):
    pass


def get_server_prices(vendor):
    pass


def get_server_prices_spot(vendor):
    pass


def get_storage_prices(vendor):
    pass


def get_traffic_prices(vendor):
    pass


def get_ipv4_prices(vendor):
    pass
```
