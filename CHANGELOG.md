## v0.1.3 (May 7, 2024)

New feature(s):

- Add `api_reference` and `display_name` to `Datacenter`, `Zone`, and `Server`.
- Add latitude and longitude coordinates to `Datacenter`.
- Add `family` to `Server`.

## v0.1.2 (Apr 24, 2024)

New vendor(s):

- Google Cloud Platform (GCP)

New feature(s):

- SVG logo for all supported vendors.

Fix(es):

- Amazon Web Services' missed outbound traffic prices
- Hetzner Cloud's outbound traffic price per GB instead of TB
- Hetzner Cloud's `datacenter_id` reference in the server prices table

## v0.1.1 (Apr 12, 2024)

New vendors:

- Hetzner Cloud

Infrastructure:

- Use Alembic for database migrations.

CLI tools:

- Database migration helpers.
- Moved CREATE TABLE generator subcommand under `schemas create`.

Database migrations:

- Add `description` field to `Server`.
- Update `Server.cpu_cores` to be optional.

‼ Breaking changes:

As the database migration tool was just introduced, if you have
been already using SC Crawler to initialize a database and
collect data (e.g. in SCD tables), you will need to let Alembic
know that you are already on v0.1.0 via the below command:

```sh
sc-crawler schemas stamp --revision 98894dffd37c
```

## v0.1.0 (Apr 05, 2024)

Initial PyPI release of `sparecores-crawler`.

CLI tools:

- Generate database schema for standard and SCD tables of the
  supported records in various SQL dialects.
- Pull records from vendor APIs and update a database with the fetched
  records.
- Copy all supported tables from a database into another one.
- Sync records of a database into another database's standard or SCD
  tables, with optional logging of the changes.
- Hash database content.

Supported vendors:

- Amazon Web Services (AWS)

Supported records:

- country
- compliance_framework
- vendor
- vendor_compliance_link
- datacenter
- zone
- server
- server_price
- storage
- storage_price
- traffic_price
- ipv4_price

Infrastructure:

- Package documentation via MkDocs, Material for MkDocs,
  `mkdocstrings`, and bunch of other MkDocs plugins.
- Database documentation on table schemas, relations and column
  comments via DBML and dbdocs.
- Unit tests via `pytest`.
- Linting via `ruff`.
