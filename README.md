This is a playground.

Get all data into a SQLite file:

```shell
rm sc_crawler.db & sc-crawler pull --cache --log-level DEBUG
```

Read from DB:

```py
from sc_crawler.database import engine
from sc_crawler.schemas import Server
from sqlmodel import Session, select
session = Session(engine)
session.exec(select(Server).where(Server.id == 'trn1.32xlarge')).one()

server = session.exec(select(Server).where(Server.id == 'trn1.32xlarge')).one()
pp(server)
pp(server.vendor)
```

Lower level access examples:

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

Debug raw AWS responses:

```py
products = aws._methods.get_products()
pp(products[1]["product"])

instance_types = aws._methods.describe_instance_types(region="us-west-2")
pp(instance_types[1])
```

## TODO

- describe how to set up auth for each vendor
- list required IAM permissions for each vendor
