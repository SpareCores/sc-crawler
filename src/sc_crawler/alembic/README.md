# Alembic Notes

## Migration History

Due to inconsistencies in the previous Alembic migration scripts, they were rewritten from scratch.

Old migration files are available in the `versions.old/` directory in git commit `1fa9862b`.
This directory was deleted in commit `4d293b92`.

## SQL Compatibility

The positioning of newly created columns is problematic because of foreign keys — table drop and
recreation is needed to achieve it. Because of that, new columns are added at the end of the tables
when foreign keys prevent recreation (i.e. on non-SCD databases that do not support table recreation,
such as PostgreSQL).
