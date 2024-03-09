from pytest import raises
from sc_crawler.str import extract_last_number, snake_case


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
