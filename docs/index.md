## Spare Cores Crawler

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
sc-crawler schema --dialect mysql
```

See `sc-crawler schema --help` for all supported database engines
(mainly thanks to SQLAlchemy), and other options.

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
sc-crawler pull --connection-string sqlite:///sc-data-all.db --include-vendor aws
```

Such an up-to-date SQLite database is managed by the Spare Cores team in the
[SC Data](https://github.com/SpareCores/sc-data) repository, or you can also
find it at <https://sc-data-public-40e9d310.s3.amazonaws.com/sc-data-all.db.bz2>.

Example run:

<div id="asciicast-sc-crawler-pull-demo" style="z-index: 1; position: relative; max-width: 80%;"></div>

### Hash data

Database content can be hashed via the `sc-crawler hash` command. It will provide
a single SHA1 hash value based on all records of all SC Crawler tables, which is
useful to track if database content has changed.

```shell
$ sc-crawler hash --connection-string sqlite:///sc-data-all.db
b13b9b06cfb917b591851d18c824037914564418
```

For advanced usage, check [sc_crawler.utils.hash_database][] to hash tables or rows.

### Copy and sync data

To copy data from a database to another one or sync data between two databases, you can use the `copy` and `sync` subcommands, which also support feeding SCD tables.

<div id="asciicast-sc-crawler-sync-demo" style="z-index: 1; position: relative; max-width: 80%;"></div>
<script>
  window.onload = function(){
    AsciinemaPlayer.create(
      '/sc-crawler-pull.cast',
      document.getElementById('asciicast-sc-crawler-pull-demo'));
    AsciinemaPlayer.create(
      '/sc-crawler-sync.cast',
      document.getElementById('asciicast-sc-crawler-sync-demo'));
}
</script>

## ORM

SC Crawler is using [SQLModel](https://sqlmodel.tiangolo.com/) /
[SQLAlchemy](https://docs.sqlalchemy.org/) as the ORM to interact with the underlying
database, and you can also use the defined schemas and models to actually read/filter
a previously pulled DB. Quick examples:

```py hl_lines="6"
from sc_crawler.tables import Server
from sqlmodel import create_engine, Session, select

engine = create_engine("sqlite:///sc-data-all.db") # (1)!
session = Session(engine) # (2)!
server = session.exec(select(Server).where(Server.server_id == 'trn1.32xlarge')).one() # (3)!

from rich import print as pp # (4)!
pp(server)
pp(server.vendor) # (5)!
```

1. Creating a [connection (pool)][sqlalchemy.create_engine] to the SQLite database.
2. Define an [in-memory representation of the database][sqlalchemy.orm.Session] for the ORM objects.
3. Query the database for the [Server][sc_crawler.tables.Server] with the `trn1.32xlarge` id.
4. Use `rich` to pretty-print the objects.
5. The `vendor` is a [Vendor][sc_crawler.tables.Vendor] relationship of the [Server][sc_crawler.tables.Server], in this case being [aws][sc_crawler.vendors.aws].
