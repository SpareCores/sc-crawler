import pytest
from sc_crawler.lookup import compliance_frameworks
from sc_crawler.utils import chunk_list, float_inf_to_str, scmodels_to_dict


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
