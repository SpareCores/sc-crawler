## Spare Cores Crawler

Note that this repository is still in pre-alpha phase, and is NOT intended for any public use yet.
Please check back by the end of Q1 2024, or contact us (via a GitHub ticket) if you are interested
in alpha/beta testing.

## TODO

- [ ] describe how to set up auth for each vendor
- [ ] list required IAM permissions for each vendor

### Database schema

Database schema visualized and documented at https://dbdocs.io/spare-cores/sc-crawler

### Usage

Generate `CREATE TABLE` statements for a MySQL database:

```shell
sc-crawler schema mysql
```

Fetch and standardize datacenter, zone, products etc data into a single SQLite file:

<details>

<summary>Required permissions for AWS</summary>

You will need the following IAM permissions to be able to run the Crawler in AWS:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowCrawler",
            "Effect": "Allow",
            "Action": [
                "pricing:ListPriceLists",
                "pricing:GetPriceListFileUrl",
                "pricing:GetProducts",
                "ec2:DescribeRegions",
                "ec2:DescribeAvailabilityZones",
                "ec2:DescribeInstanceTypes"
            ],
            "Resource": "*"
        }
    ]
}
```

</details>

```shell
rm sc_crawler.db; sc-crawler pull --cache --log-level DEBUG --include-vendor aws
```

### Other WIP methods

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
