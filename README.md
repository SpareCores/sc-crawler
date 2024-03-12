## Spare Cores Crawler

!!! note

    This repository is still in alpha phase, and is NOT intended for any
    public use yet.  Please check back by the end of Q1 2024, or contact
    us (via a [GitHub ticket](https://github.com/SpareCores/sc-crawler/issues/new))
    if you are interested in alpha/beta testing.

## Database schema

Database schema visualized and documented at <https://dbdocs.io/spare-cores/sc-crawler>.

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

See `sc-crawler schema --help` for all supported database engines.

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

Fetch and standardize datacenter, zone, servers, traffic, storage etc data from AWS into a single SQLite file:

```shell
sc-crawler pull --include-vendor aws
```

Such an up-to-date SQLite database is managed by the Spare Cores team in the
[SC Data](https://github.com/SpareCores/sc-data) repository, or you can also
find it at <https://sc-data-public-40e9d310.s3.amazonaws.com/sc-data-all.db.bz2>.

## Other WIP methods

Read from previously pulled DB:

```py
from sc_crawler.schemas import Server
from sqlmodel import create_engine, Session, select

engine = create_engine("sqlite:///sc_crawler.db")
session = Session(engine)
server = session.exec(select(Server).where(Server.id == 'trn1.32xlarge')).one()

from rich import print as pp
pp(server)
pp(server.vendor)
```
