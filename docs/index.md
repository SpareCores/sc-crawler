## Spare Cores Crawler

!!! note annotate

    This repository is still in alpha phase(1), and is NOT intended for any
    public use yet.

    Please check back by the end of Q1 2024, or contact us (via a
    [GitHub ticket](https://github.com/SpareCores/sc-crawler/issues/new))
    if you are interested in alpha/beta testing.

1. "The software has the minimal required set of features to be useful. The architecture of the software is clear." Source: [Stages of Software Development](https://martin-thoma.com/software-development-stages/#3-alpha)

SC Crawler is a Python package to pull and standardize data on cloud
compute resources, with tooling to help organize and update the
collected data into databases.

## Database schemas

The database schemas and relationships are visualized and documented at
<https://dbdocs.io/spare-cores/sc-crawler>.

## Usage

The package provides a CLI tool:

```shell
sc-crawler --help
```

### Print table definitions

Generate `CREATE TABLE` statements e.g. for a MySQL database:

```shell
sc-crawler schema mysql
```

See `sc-crawler schema --help` for all supported database engines,
mainly thanks to SQLAlchemy.

### Collect data

Note that you need specific IAM permissions to be able to run `sc-crawler` at the below vendors:

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
                "ec2:DescribeInstanceTypes",
                "ec2:DescribeSpotPriceHistory"
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

### Hash data

Database content can be hashed via the `sc-crawler hash` command. It will provide
a single SHA1 hash value based on all records of all SC Crawler tables, which is
useful to track if database content has changed.

For advanced usage, check [sc_crawler.utils.hash_database][] to hash tables or rows.

## ORM

SC Crawler is using [SQLModel](https://sqlmodel.tiangolo.com/) /
[SQLAlchemy](https://docs.sqlalchemy.org/) as the ORM to interact with the underlying
database, and you can also use the defined schemas and models to actually read/filter
a previously pulled DB. Quick examples:

```py hl_lines="6"
from sc_crawler.schemas import Server
from sqlmodel import create_engine, Session, select

engine = create_engine("sqlite:///sc_crawler.db") # (1)!
session = Session(engine) # (2)!
server = session.exec(select(Server).where(Server.server_id == 'trn1.32xlarge')).one() # (3)!

from rich import print as pp # (4)!
pp(server)
pp(server.vendor) # (5)!
```

1. Creating a [connection (pool)][sqlalchemy.create_engine] to the SQLite database.
2. Define an [in-memory representation of the database][sqlalchemy.orm.Session] for the ORM objects.
3. Query the database for the [Server][sc_crawler.schemas.Server] with the `trn1.32xlarge` id.
4. Use `rich` to pretty-print the objects.
5. The `vendor` is a [Vendor][sc_crawler.schemas.Vendor] relationship of the [Server][sc_crawler.schemas.Server], in this case being [aws][sc_crawler.vendors.aws].
