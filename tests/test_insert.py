from sc_crawler.insert import wrap


def test_wrap_default_suffix():
    assert wrap() == ""


def test_wrap_empty_suffix():
    assert wrap("") == ""


def test_wrap_with_suffix():
    assert wrap("hello") == " [hello]"


def test_wrap_with_whitespace_suffix():
    assert wrap("   world") == " [   world]"
