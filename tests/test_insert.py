from sc_crawler.insert import wrap


def test_wrap_default_text():
    assert wrap() == ""


def test_wrap_empty_text():
    assert wrap("") == ""


def test_wrap_with_text():
    assert wrap("foo") == " foo "


def test_wrap_with_whitespace():
    assert wrap("   foobar") == "    foobar "


def test_wrap_with_before_after():
    assert wrap("foo", before="__", after="__") == "__foo__"
