## v0.3.x (development version, unreleased on PyPI)

Fix(es):

- Add support for Azure Denmark East region (Copenhagen).
- Fix SCD table schema generation in CLI `create` command.
- Replace deprecated `datetime.utcnow()` calls with `datetime.now(UTC)`.
- Add field serializers to `cpus`, `gpus`, `storages`, and `price_tiered` columns to prevent Pydantic serialization
  warnings.
- Fix and extend test cases for field serializers and OVH vendor module.
- Add Provisioned IOPS (io1, io2) storage types and update gp3 volume limits (IOPS, throughput, size) for AWS.

New feature(s):

- Record the monthly cap for ondemand prices.

‼ Breaking changes:

- Minimum required Python version upgraded from 3.9 to 3.11.

## v0.3.4 (Feb 05, 2026)

Fix(es):

- Add storage infos from lshw outputs to GCP servers.
- Check region availability for Alibaba Cloud servers before adding their prices.
- Determine CPU allocation type for Alibaba Cloud servers.
- Preserve vendor API data by default, only overriding when necessary for known API data issues.
- Verify Alibaba Cloud instance type retirement status.
- Prevent duplicate records from being inserted into the database.

New feature(s):

- CLI tool to dump database tables to JSON files.
- Implement Alibaba Cloud's spot instance price sampling.
- Support for fractional GPU counts in server instances with partial GPU allocation.

Housekeeping:

- Delay method validation to avoid CLI startup slowdown.
- Avoid name conflict in vendor modules via private modules.
- Convert all prices to float and round to 4 digits.
- Change gpu_count field type from integer to float for fractional GPU support.
- Remove foreign key constraints from SCD table definitions.
- Reset Alembic revision history and rewrite initial migration script.

## v0.3.3 (Jan 02, 2026)

New vendor(s):

- Alibaba Cloud

Fix(es):

- Don't include instruction cache in L1 cache size.
- Manufacturer of Ampere Altra.

## v0.3.2 (Dec 04, 2025)

New vendor(s):

- UpCloud
- OVHcloud

New benchmark(s):

- PassMark
- LLM inference speed

Fix(es):

- Minor region and server detail overrides.

## v0.3.1 (Oct 25, 2024)

New benchmark(s):

- Static HTTP server
- Redis
- stress-ng's div16 run on all vCPUs

New feature(s):

- Optional list of tables to be synced in the CLI tool.
- Standardized CPU and GPU manufacturer, family, and model name.
- Optional description for Disks.

Fix(es):

- Better support for long-running DB syncs.
- Exlude dummy "2 Ghz" CPU speed reported by GCP.
- Improved physical CPU cores lookup.
- Improved performance for interactive bulk inserts.
- Review how vendors reports on storage size using base 2 or 10.
- Update from Azure's deprecated API endpoint, fix ingesting NVMe drives.
- Better support for Azure API rate limits.

## v0.3.0 (Aug 20, 2024)

New vendor(s):

- Microsoft Azure

New feature(s):

- Support for new `hcloud` CX server types.
- Support for new `hcloud` region (Singapore).
- Improved caching.

Fix(es):

- Join references pointing to the right tables.
- Count CPU cores in all physical CPUs.
- Improve the standardization and cleanup of the CPU manufacturer, family, and model.
- Extract speed from CPU description when available instead of unreliable `dmidecode` data.
- Update included outbound network extractor at `hcloud` due to API change.
- Check if a server is available in a `gcp` zone even though a related price is known.
- Silence `SAWarning` on multiple relationships using overlapping compound foreign keys.
- Fix manually collected geolocation of 3 `gcp` regions.
- Fix spelling issues in benchmark and table column descriptions.

‼ Breaking changes:

- Complex queries with joins relying on the foreign keys of the table
  definitions are now using the right references. This might result in
  different (but correct) results than before.

## v0.2.1 (June 4, 2024)

Fix(es):

- Sort `dict` by its keys before passing as JSON to the database engine.

## v0.2.0 (June 4, 2024)

Database migrations:

- Name all constraints for easier management in the future.
- Rename the `datacenter` table to `region`, and the `datacenter_id`
  column to `region_id` in the `zone`, `server_price`,
  `storage_price`, `traffic_price` and `ipv4_price` tables.

‼ Breaking changes:

- Renamed Datacenter to Region in all tables and across the codebase.

## v0.1.4 (June 2, 2024)

New feature(s):

- Documented `benchmark` workloads and actual `benchmark_score` records loaded from `sparecores-inspector-data`.
- Enriched `server` details loaded from `sparecores-inspector-data`.

Database migrations:

- Add `benchmark` and `benchmark_score` tables.
- Add 8 new columns to the `server` table.

‼ Breaking changes:

- Renamed the `memory` column to `memory_amount` in the `server` table.

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
