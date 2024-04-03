from enum import Enum
from hashlib import sha1
from json import dumps
from math import isinf
from typing import Any, Dict, Iterable, List, Optional, Union

from rich.progress import Progress
from sqlmodel import Session, create_engine, select

from .table_bases import ScModel


def jsoned_hash(*args, **kwargs):
    """Hash the JSON-dump of all positional and keyword arguments.

    Examples:
        >>> jsoned_hash(42)
        '0211c62419aece235ba19582d3cf7fd8e25f837c'
        >>> jsoned_hash(everything=42)
        '8f8a7fcade8cb632b856f46fc64c1725ee387617'
        >>> jsoned_hash(42, 42, everything=42)
        'f04a77f000d85929b13de04b436c60a1272dfbf5'
    """
    return sha1(
        dumps({"args": args, "kwargs": kwargs}, sort_keys=True).encode()
    ).hexdigest()


class HashLevels(Enum):
    DATABASE = "database"
    TABLE = "table"
    ROW = "row"


def hash_database(
    connection_string: str,
    level: HashLevels = HashLevels.DATABASE,
    ignored: List[str] = ["observed_at"],
    progress: Optional[Progress] = None,
) -> Union[str, dict]:
    """Hash the content of a database.

    Args:
        connection_string: SQLAlchemy connection string to connect to the database.
        level: The level at which to apply hashing. Possible values are 'DATABASE' (default), 'TABLE', or 'ROW'.
        ignored: List of column names to be ignored during hashing.
        progress: Optional progress bar to track the status of the hashing.

    Returns:
        A single SHA1 hash or dict of hashes, depending on the level.
    """
    from .tables import tables

    if progress:
        tables_task_id = progress.add_task("Hashing tables", total=len(tables))

    engine = create_engine(connection_string)

    with Session(engine) as session:
        hashes = {}
        for table in tables:
            table_name = table.get_table_name()
            hashes[table_name] = table.hash(session, ignored=ignored, progress=progress)
            if progress:
                progress.update(tables_task_id, advance=1)

    if level == HashLevels.TABLE:
        hashes = {k: jsoned_hash(v) for k, v in hashes.items()}

    if level == HashLevels.DATABASE:
        hashes = jsoned_hash(hashes)

    return hashes


def chunk_list(items: List[Any], size: int) -> Iterable[List[Any]]:
    """Split a list into chunks of a specified size.

    Examples:
        >>> [len(x) for x in chunk_list(range(10), 3)]
        [3, 3, 3, 1]
    """
    for i in range(0, len(items), size):
        yield items[i : i + size]


def scmodels_to_dict(scmodels: List[ScModel], keys: List[str]) -> Dict[str, ScModel]:
    """Creates a dict indexed by key(s) of the ScModels of the list.

    When multiple keys are provided, each ScModel instance will be stored in
    the dict with all keys. If a key is a list, then each list element is
    considered (not recursively, only at first level) as a key.
    Conflict of keys is not checked.

    Args:
        scmodels: list of ScModel instances
        keys: a list of strings referring to ScModel fields to be used as keys

    Examples:
        >>> from sc_crawler.vendors import aws
        >>> scmodels_to_dict([aws], keys=["vendor_id", "name"])
        {'aws': Vendor...
    """
    data = {}
    for key in keys:
        for scmodel in scmodels:
            data_keys = getattr(scmodel, key)
            if not isinstance(data_keys, list):
                data_keys = [data_keys]
            for data_key in data_keys:
                data[data_key] = scmodel
    return data


def is_sqlite(session: Session) -> bool:
    """Checks if a SQLModel session is binded to a SQLite database."""
    return session.bind.dialect.name == "sqlite"


def is_postgresql(session: Session) -> bool:
    """Checks if a SQLModel session is binded to a PostgreSQL-like database.

    Dialect name is checked for PostgreSQL or CockroachDB."""
    return session.bind.dialect.name in ["postgresql", "cockroachdb"]


def float_inf_to_str(x: float) -> Union[float, str]:
    """Transform to string if a float is inf."""
    return "Infinity" if isinf(x) else x


def table_name_to_model(table_name: str) -> ScModel:
    """Return the ScModel schema for a table name."""
    from .tables import tables

    return [t for t in tables if t.get_table_name() == table_name][0]


def get_row_by_pk(session: Session, model: ScModel, pks: dict) -> ScModel:
    """Get a row from a table definition by primary keys.

    Args:
        session: Connection for database connections.
        model: An ScModel schema definition with table reference.
        pks: Dictionary of all the primary keys for the row,.

    Returns:
        ScModel object read from the database.
    """
    q = select(model)
    for k, v in pks.items():
        q = q.where(getattr(model, k) == v)
    return session.exec(statement=q).one()
