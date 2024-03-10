from sc_crawler.utils import chunk_list


def test_chunk_list():
    res = [list(x) for x in chunk_list(range(10), 3)]
    assert len(res) == 4
    assert res[0] == [0, 1, 2]
    assert res[3] == 9
