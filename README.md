This is a playground.

Examples:

```py
from sc_crawler.vendors import aws
aws.get_all()  # slow to query all instance types in all regions
aws.datacenters
aws.zones

from rich import print as pp
pp(aws)
pp(aws._datacenters[1]._zones)
pp(aws._servers.get("t3a.2xlarge"))
pp(aws._servers.get("c5d.large"))
```
