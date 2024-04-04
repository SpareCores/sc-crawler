from pytest import raises
from sc_crawler.str_utils import extract_last_number, snake_case, space_after, wrap


def test_wrap_no_text():
    with raises(TypeError):
        wrap()


def test_wrap_empty_text():
    assert wrap("") == ""


def test_wrap_with_text():
    assert wrap("foo") == " foo "


def test_wrap_with_whitespace():
    assert wrap("   foobar") == "    foobar "


def test_wrap_with_before_after():
    assert wrap("foo", before="__", after="__") == "__foo__"


def test_space_after_no_text():
    with raises(TypeError):
        space_after()


def test_space_after_text():
    assert space_after("foo") == "foo "


def test_extract_last_number():
    assert extract_last_number("foo42") == 42.0
    assert extract_last_number("foo24.42bar") == 24.42
    assert extract_last_number("foobar") is None
    assert extract_last_number("abc123def456") == 456.0
    assert extract_last_number("42.42 24 1.23") == 1.23
    assert extract_last_number("") is None
    with raises(TypeError):
        extract_last_number(None)
        extract_last_number(42)


def test_snake_case():
    assert snake_case("DescriptionToComment") == "description_to_comment"
    assert snake_case("AnotherExample") == "another_example"
    assert snake_case("OneMoreTest") == "one_more_test"
    assert snake_case("") == ""
