## Spare Cores Crawler

Note that this repository is still in pre-alpha phase, and is NOT intended for any public use yet.
Please check back by the end of Q1 2024, or contact us (via a GitHub ticket) if you are interested
in alpha/beta testing.

## TODO

- [ ] describe how to set up auth for each vendor
- [ ] list required IAM permissions for each vendor
- [ ] implement vendors
    - [x] AWS
    - [ ] GCP
    - [ ] Azure
    - [ ] Scaleway
    - [ ] Hetzner
    - [ ] OVH
    - [ ] add others ...

## Database schema

Database schema visualized and documented at https://dbdocs.io/spare-cores/sc-crawler

## Usage

The package provides a CLI tool:

```shell
sc-crawler --help
```

### Print table definitions

Generate `CREATE TABLE` statements for a MySQL database:

```shell
sc-crawler schema mysql
```

See `sc-crawler schema` for all supported database engines.

### Collect data

Note that you need specific IAM permissions to be able to run the Crawler at the below vendors:

<details>

<summary>Amazon Web Services (AWS)</summary>

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


Fetch and standardize datacenter, zone, products etc data into a single SQLite file:

```shell
rm sc_crawler.db; sc-crawler pull --cache --log-level DEBUG --include-vendor aws
```

## Other WIP methods

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
