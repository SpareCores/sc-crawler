from enum import Enum
from hashlib import sha1
from json import dumps
from typing import List, Union

from sqlmodel import Session, create_engine

from .schemas import tables


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
