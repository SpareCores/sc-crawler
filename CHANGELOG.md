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

- Amazon Web Services

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
