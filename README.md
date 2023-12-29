This is a playground.

Examples:

```py
from sc_crawler.vendors import aws

# enable persistent caching of AWS queries
from cachier import set_default_params
set_default_params(caching_enabled=True)

# fetch data
aws.get_all()  # slow to query all instance types in all regions

# look around
aws.datacenters
aws.zones

# pretty printed objects
from rich import print as pp
pp(aws)
pp(aws._datacenters[1]._zones)
pp(aws._servers.get("t3a.2xlarge"))
pp(aws._servers.get("i3en.12xlarge"))
pp(aws._servers.get("g4dn.metal"))
```
