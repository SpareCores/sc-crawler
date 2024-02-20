from re import search, sub


# https://www.w3resource.com/python-exercises/string/python-data-type-string-exercise-97.php
def snake_case(text):
    """Convert CamelCase to snake_case.

    Examples:
        >>> snake_case('DescriptionToComment')
        'description_to_comment'
    """
    return "_".join(sub("([A-Z][a-z]+)", r" \1", text).split()).lower()


# https://www.tutorialspoint.com/python-program-to-convert-singular-to-plural
def plural(text):
    """Super basic implementation of pluralizing an English word.

    Note that grammar exceptions are not handled, so better to use a
    proper NLP method for real use-cases.

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
