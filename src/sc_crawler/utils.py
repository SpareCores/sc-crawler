from enum import Enum
from hashlib import sha1
from json import dumps
from typing import Any, Dict, Iterable, List, Union

from sqlmodel import Session, create_engine

from .schemas import ScModel, tables


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
) -> Union[str, dict]:
    """Hash the content of a database.

    Args:
        connection_string: SQLAlchemy connection string to connect to the database.
        level: The level at which to apply hashing. Possible values are 'DATABASE' (default), 'TABLE', or 'ROW'.
        ignored: List of column names to be ignored during hashing.

    Returns:
        A single SHA1 hash or dict of hashes, depending on the level.
    """
    engine = create_engine(connection_string)

    with Session(engine) as session:
        hashes = {
            table.get_table_name(): table.hash(session, ignored=ignored)
            for table in tables
        }

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


def scmodels_to_dict(
    scmodels: List[ScModel], keys: List[str] = ["id"]
) -> Dict[str, ScModel]:
    """Creates a dict indexed by key(s) of the elements of the list.

    When multiple keys are provided, an ScModel instance will be stored in
    the dict with all keys. Conflict of keys is not checked.

    Args:
        scmodels: list of ScModel instances
        key: a list of strings referring to ScModel fields to be used as keys

    Examples:
        >>> scmodels_to_dict([aws], keys=["id", "name"])
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
    """Checks if a SQLModel session is binded to SQLite or other database."""
    return session.bind.dialect.name == "sqlite"
