"""Cloud compute resource vendors."""


class Vendor(object):
    """Base class for cloud compute resource vendors."""

    name: str = NotImplemented
    logo: str = NotImplemented
    homepage: str = NotImplemented
    location = str None
    found_date = NotImplemented
