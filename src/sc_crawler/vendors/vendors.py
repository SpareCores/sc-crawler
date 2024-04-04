"""Supported cloud and VPS provider vendors."""

from ..lookup import countries
from ..tables import Vendor

aws = Vendor(
    vendor_id="aws",
    name="Amazon Web Services",
    homepage="https://aws.amazon.com",
    country=countries["US"],
    state="Washington",
    city="Seattle",
    address_line="410 Terry Ave N",
    zip_code="98109",
    founding_year=2002,
    status_page="https://health.aws.amazon.com/health/status",
)
"""Amazon Web Services."""

gcp = Vendor(
    vendor_id="gcp",
    name="Google Cloud Platform",
    homepage="https://cloud.google.com",
    country=countries["US"],
    state="California",
    city="Mountain View",
    address_line="1600 Amphitheatre Pkwy",
    zip_code="94043",
    founding_year=2008,
    status_page="https://status.cloud.google.com/",
)
"""Google Cloud Platform."""
