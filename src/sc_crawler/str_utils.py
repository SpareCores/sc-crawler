from re import search, sub
from typing import Union


def wrap(text: str, before: str = " ", after: str = " ") -> str:
    """Wrap string between before/after strings (default to spaces) if not empty.

    Args:
        text: A string.
        before: Characters to be added before the `text`.
        after: Characters to be added after the `text`.
    """
    return text if text == "" else before + text + after


def space_after(text: str) -> str:
    """Add space after string if not empty."""
    return wrap(text, before="")


# https://www.w3resource.com/python-exercises/string/python-data-type-string-exercise-97.php
def snake_case(text: str) -> str:
    """Convert CamelCase to snake_case.

    Args:
        text: A CamelCase text.

    Returns:
        snake_case version of the text.

    Examples:
        >>> snake_case('DescriptionToComment')
        'description_to_comment'
    """
    return "_".join(sub("([A-Z][a-z]+)", r" \1", text).split()).lower()


# https://www.tutorialspoint.com/python-program-to-convert-singular-to-plural
def plural(text: str) -> str:
    """Super basic implementation of pluralizing an English word.

    Note that grammar exceptions are not handled, so better to use a
    proper NLP method for real use-cases.

    Args:
        text: A singular noun.

    Returns:
        Plural form of the noun.

    Examples:
        >>> plural('dog')
        'dogs'
        >>> plural('boy') # :facepalm:
        'boies'
    """
    if search("[sxz]$", text) or search("[^aeioudgkprt]h$", text):
        return sub("$", "es", text)
    if search("[aeiou]y$", text):
        return sub("y$", "ies", text)
    return text + "s"


def extract_last_number(text: str) -> Union[float, None]:
    """Extract the last non-negative number from a string.

    Args:
        text: The input string from which to extract the number.

    Returns:
        The last non-negative number found in the string, or None if no number is found.

    Examples:
        >>> extract_last_number("foo42")
        42.0
        >>> extract_last_number("foo24.42bar")
        24.42
    """
    match = search(r"([\d\.]+)[^0-9]*$", text)
    return float(match.group(1)) if match else None
