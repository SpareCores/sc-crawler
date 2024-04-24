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

### Collect data

Note that you need specific IAM permissions to be able to run `sc-crawler` at the below vendors:

<details markdown="1">

<summary>Amazon Web Services (AWS)</summary>

AWS supports different options for [Authentication and access](https://docs.aws.amazon.com/sdkref/latest/guide/access.html) for interacting with their APIs. This is usually an AWS access key stored in `~/.aws/credentials` or in environment variables, or an attached IAM role.

The related user or role requires the below minimum IAM policy:

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

<details markdown="1">

<summary>Google Cloud Platform (GCP)</summary>

Using the [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) for interacting with GCP APIs. This is usually the path to a credential configuration file (created at <https://developers.google.com/workspace/guides/create-credentials#service-account>) stored in the `GOOGLE_APPLICATION_CREDENTIALS` environment variable, but could be an attached service account, Workload Identity Federation etc.

The related user or service account requires the below minimum roles:

- Commerce Price Management Viewer
- Compute Viewer

List of APIs required to be enabled in the project:

- [Cloud Billing API](https://console.cloud.google.com/apis/library/cloudbilling.googleapis.com)
- [Compute Engine API](https://console.developers.google.com/apis/api/compute.googleapis.com/overview)

</details>

<details markdown="1">

<summary>Hetzner Cloud</summary>

Generate token at your Hetzner Cloud project and store it in the `HCLOUD_TOKEN` environment variable.

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
      'sc-crawler-pull.cast',
      document.getElementById('asciicast-sc-crawler-pull-demo'));
    AsciinemaPlayer.create(
      'sc-crawler-sync.cast',
      document.getElementById('asciicast-sc-crawler-sync-demo'));
}
</script>

### Database migrations

To generate `CREATE TABLE` statements using the current version of the Crawler schemas,
e.g. for a MySQL database:

```shell
sc-crawler schemas create --dialect mysql
```

See `sc-crawler schemas create --help` for all supported database engines
(mainly thanks to SQLAlchemy), and other options.

`sc-crawler schemas` also supports many other subcommands based on Alembic,
e.g. `upgrade` or `downgrade` schemas in a database (either just printing
the related SQL commands via the `--sql` flag), printing the current version,
setting a database version to a specific revision, or auto-generating migration
scripts (for SC Crawler developers).

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
