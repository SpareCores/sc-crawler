## Vendor-specific crawler tools

Each file in this folder provides the required helpers for a given vendor, named as the identifier of the vendor.
For example, `aws.py` provides functions to be used by its `Vendor` instance, called `aws`.

Each file should provide the below functions:

- `get_compliance_frameworks`: define `VendorComplianceLink` instances
- `get_datacenters`: define `Datacenter` instances
- `get_zones`: define `Zone` instances
- `get_servers`: define `Server` instances
- `get_server_prices`: define `ServerPrice` instances
- `get_storage_prices`: define `StoragePrice` instances
- `get_traffic_prices`: define `TrafficPrice` instances
- `get_ipv4_prices`: define `Ipv4Price` instances

Each function will be picked up as `Vendor` instance methods, so each function should take a single argument, that is the `Vendor` instance. No need to return the objects -- it's enough to define the above-mentioned instances.

There are also a `get_prices` and `get_all` instance method defined for each `Vendor`, which wrappers call the pricing-related or all the above helpers in the above-listed order.

If a helper is not needed (e.g. another helper already provides its output, or there are no spot prices), it is still required, but can return early, e.g. if `Zone` objects were populated by `get_datacenters` already, do something like:

```python
def get_zones(self):
    """Zones were already provided in get_datacenters."""
    pass
```

Other functions and variables must be prefixed with an underscore to suggest those are internal tools.

## Template file for new vendors

```python
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


def get_storage_prices(vendor):
    pass


def get_traffic_prices(vendor):
    pass


def get_ipv4_prices(vendor):
    pass
```
