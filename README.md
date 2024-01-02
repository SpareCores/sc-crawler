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
pp(aws.datacenters)
pp(aws.servers[0])
```

Or simply run:

```shell
rm /tmp/sc_crawler.db & python -m sc_crawler.app
```
