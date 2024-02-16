from enum import Enum
from hashlib import sha1
from json import dumps
from sqlmodel import Session, create_engine
from typing import List, Union

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
    """Hash the content of a database."""
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
