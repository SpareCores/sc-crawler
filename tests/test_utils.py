from datetime import date, datetime

import pytest
from sqlalchemy import JSON, Enum
from sqlmodel import Session

from sc_crawler.lookup import compliance_frameworks
from sc_crawler.table_fields import HashableJSON
from sc_crawler.tables import tables
from sc_crawler.utils import (
    chunk_list,
    create_sc_engine,
    float_inf_to_str,
    scmodels_to_dict,
)


def test_chunk_list():
    res = [list(x) for x in chunk_list(range(10), 3)]
    assert len(res) == 4
    assert res[0] == [0, 1, 2]
    assert res[3] == [9]


def test_scmodels_to_dict_by_single_id():
    cflist = [v for _, v in compliance_frameworks.items()]
    cfdict = scmodels_to_dict(cflist, keys=["compliance_framework_id"])
    assert isinstance(cfdict, dict)
    assert len(cfdict) == len(cflist)
    assert list(cfdict.items())[0][1] == cflist[0]


def test_scmodels_to_dict_by_multiple_ids():
    cflist = [v for _, v in compliance_frameworks.items()]
    cfdict = scmodels_to_dict(cflist, keys=["compliance_framework_id", "abbreviation"])
    assert len(cfdict) == len(cflist) * 2
    assert list(cfdict.items())[0][1] == cflist[0]


def test_float_inf_to_str():
    assert float_inf_to_str(42) == 42
    assert float_inf_to_str(float(42)) == 42.0
    assert float_inf_to_str(float("Infinity")) == "Infinity"
    assert float_inf_to_str(float(1e9999)) == "Infinity"
    with pytest.raises(TypeError):
        assert float_inf_to_str("Infinity") == "Infinity"


def _sample_value(table, column):
    """A non-null value for the scalar column types used in the schema."""
    if isinstance(column.type, (JSON, HashableJSON)):
        # loaded rows validate their JSON columns, so use null or an empty value
        if column.nullable:
            return None
        field = table.model_fields[column.name]
        if field.default_factory:
            return field.default_factory().model_dump()
        return []
    if isinstance(column.type, Enum):
        return column.type.enum_class[column.type.enums[0]]
    try:
        python_type = column.type.python_type
    except NotImplementedError:  # AutoString
        python_type = str
    return {
        bool: True,
        date: date(2026, 1, 1),
        datetime: datetime(2026, 1, 1, 12),
        float: 1.5,
        int: 1,
        str: "foo",
    }[python_type]


@pytest.mark.parametrize("table", tables, ids=lambda t: t.get_table_name())
def test_hash_all_column_types(table):
    """Hashing must serialize every column type, incl. the non-null optional ones."""
    engine = create_sc_engine("sqlite://")
    table.__table__.create(engine)
    with Session(engine) as session:
        session.execute(
            table.__table__.insert().values(
                {c.name: _sample_value(table, c) for c in table.__table__.columns}
            )
        )
        session.commit()
        hashes = table.hash(session)
    assert len(hashes) == 1
    with Session(engine) as session:
        assert table.hash(session) == hashes
