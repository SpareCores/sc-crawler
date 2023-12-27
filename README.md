This is a playground.

Examples:

```py
from sc_crawler.vendors import aws
aws.get_datacenters()
aws.datacenters
aws.zones

from rich import print as pp
pp(aws)

pp(aws._datacenters[1]._zones)
```
