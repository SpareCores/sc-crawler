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

## Create Alembic Migration with New Table Columns

1. Before table definition modification, run the following commands on an empty or non-existent database:

```sh
sc-crawler schemas stamp
sc-crawler schemas autogenerate
```

It will create an Alembic migration file with complete table definitions. Move this file out of the `versions/`
directory to a safe place.

2. Create (or download) a new - typically SQLite - DB with the current revision:

```sh
sc-crawler pull
```

or (if you don't need test data):

```sh
sc-crawler schemas upgrade
```

3. Modify the table definitions in the codebase.
4. Run the following command to generate a new migration file with the modifications (with a proper message now):

```sh
sc-crawler schemas autogenerate --message "vx.y.z migration message"
```

5. From the migration file you generated in the first step, copy the table definitions (SCD and non-SCD) to the new
   migration file. You will need only the table definitions that were modified in step 3. Typically you can create
   functions
   for each modified table with a parameter `is_scd` to return both SCD and non-SCD table definitions. You will need to
   convert the table creation calls to table definitions like this:

```python
from alembic import op

op.create_table(
    "table_name",
    # ...
)
```

to

```python
import sqlalchemy as sa

sa.Table(
    "table_name",
    sa.MetaData(),
    # ...
)
```

If table definitions include Enums as column types, you will need to modify them as follows to support migrations in
both SQLite and PostgreSQL SCD databases:

```python
import sqlalchemy as sa
from alembic import op

is_postgresql = op.get_context().dialect.name == "postgresql"
table = sa.Table(
    "table_name",
    sa.MetaData(),
    sa.Column(
        "column_name",
        sa.dialects.postgresql.ENUM(
            "ENUM_VALUE_1",
            "ENUM_VALUE_2",
            "ENUM_VALUE_3",
            name="enum_name",
            create_type=False,
        )
        if is_postgresql
        else sa.Enum(
            "ENUM_VALUE_1",
            "ENUM_VALUE_2",
            "ENUM_VALUE_3",
            name="enum_name",
        ),
    ),
)
```

Note: `create_type=False` will also work with `sa.Enum` in future versions of SQLAlchemy:
https://github.com/sqlalchemy/sqlalchemy/issues/10604

6. You will need these functions to handle SCD and non-SCD migrations and to add new columns at the correct positions in
   the tables:

```python
import sqlalchemy as sa
from alembic import op


def is_scd_migration() -> bool:
    return bool(op.get_context().config.attributes.get("scd"))


def scdize_suffix(table_name: str) -> str:
    if is_scd_migration():
        return table_name + "_scd"
    return table_name


def get_table(is_scd: bool) -> sa.Table:
    if is_scd:
        return sa.Table(
            "table_name_scd",
            sa.MetaData(),
            # ...
        )
    return sa.Table(
        "table_name",
        sa.MetaData(),
        # ...
    )


def upgrade() -> None:
    is_scd = is_scd_migration()
    table_name = scdize_suffix("table_name")
    table = get_table(is_scd)
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd

    if do_recreate_tables:
        with op.batch_alter_table(
                table,
                schema=None,
                copy_from=table,
                recreate="always",
        ) as batch_op:
            batch_op.add_column(
                sa.Column("column_name", sa.Integer(), comment="column comment"),
                insert_after="column_name_before",
            )
    else:
        op.add_column(
            table_name,
            sa.Column("column_name", sa.Integer(), comment="column comment"),
        )


def downgrade() -> None:
    is_scd = is_scd_migration()
    table = get_table(is_scd)

    with op.batch_alter_table(
            table,
            schema=None,
    ) as batch_op:
        batch_op.drop_column("column_name")
```

7. If the migration needs to modify existing data, you need to update the table definition and run the `update`
   commands on the modified table:

```python
import sqlalchemy as sa
from alembic import op


def _insert_column_after(table: sa.Table, new_col: sa.Column, after: str):
    """Insert a column into a Table's column collection after the named column."""
    cols = list(table.c)
    idx = next(i for i, c in enumerate(cols) if c.name == after) + 1
    tail = cols[idx:]
    for c in tail:
        table._columns.remove(c)
    table.append_column(new_col)
    for c in tail:
        table.append_column(c)


def upgrade() -> None:
    is_scd = is_scd_migration()
    table_name = scdize_suffix("table_name")
    table = get_table(is_scd)
    do_recreate_tables = (op.get_context().dialect.name == "sqlite") or is_scd

    if do_recreate_tables:
        with op.batch_alter_table(
                table,
                schema=None,
                copy_from=table,
                recreate="always",
        ) as batch_op:
            batch_op.add_column(
                sa.Column("column_name", sa.Integer(), comment="column comment"),
                insert_after="column_name_before",
            )
    else:
        op.add_column(
            table_name,
            sa.Column("column_name", sa.Integer(), comment="column comment"),
        )

    _insert_column_after(
        table,
        sa.Column("column_name", sa.Integer(), comment="column comment"),
        "column_name_before",
    )

    op.execute(
        table.update()
        .where(
            # ...
        )
        .values(
            # ...
        )
    )
```