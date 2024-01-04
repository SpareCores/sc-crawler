This is a playground.

Get all data into a SQLite file:

```shell
rm /tmp/sc_crawler.db & python -m sc_crawler.app
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

## TODO

- describe how to set up auth for each vendor
- list required IAM permissions for each vendor
