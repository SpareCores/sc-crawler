from sc_crawler.insert import wrap


def test_wrap_default_suffix():
    assert wrap() == ""


def test_wrap_empty_suffix():
    assert wrap("") == ""


def test_wrap_with_suffix():
    assert wrap("foo") == " [foo]"


def test_wrap_with_whitespace_suffix():
    assert wrap("   foobar") == " [   foobar]"
