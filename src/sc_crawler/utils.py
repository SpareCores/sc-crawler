from enum import Enum
from hashlib import sha1
from json import dumps
from typing import List, Union

from sqlmodel import Session, create_engine

from .schemas import tables


class HashLevels(Enum):
    DATABASE = "database"
    TABLE = "table"
    ROW = "row"


def hash_database(
    connection_string: str,
    level: HashLevels = HashLevels.DATABASE,
    ignored: List[str] = ["inserted_at"],
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
        hashes = {
            k: sha1(dumps(v, sort_keys=True).encode()).hexdigest()
            for k, v in hashes.items()
        }

    if level == HashLevels.DATABASE:
        hashes = sha1(dumps(hashes, sort_keys=True).encode()).hexdigest()

    return hashes
