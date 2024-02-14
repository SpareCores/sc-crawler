from collections import ChainMap
from hashlib import sha1
from json import dumps
from sqlalchemy.inspection import inspect
from sqlmodel import select


def hashrow(row, ignored=["inserted_at"]):
    """Return tuple of primary keys and hash of all values expect ignored columns."""
    pks = sorted([key.name for key in inspect(row.__class__).primary_key])
    rowdict = row.model_dump()
    rowkeys = tuple(rowdict.get(pk) for pk in pks)
    for dropkey in [*ignored, *pks]:
        rowdict.pop(dropkey, None)
    rowhash = sha1(dumps(rowdict, sort_keys=True).encode()).hexdigest()
    return tuple([rowkeys, rowhash])


def hashrows(rows, ignored=["inserted_at"]):
    return sorted([hashrow(row) for row in rows])


def get_rows(table, session):
    return session.exec(statement=select(table))


def get_table_name(table):
    return table.__tablename__


def get_table_names(engine):
    return inspect(engine).get_table_names()
