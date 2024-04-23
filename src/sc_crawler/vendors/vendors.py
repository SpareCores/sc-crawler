"""Supported cloud and VPS provider vendors.

For logos, see e.g. <https://iconduck.com/sets/svg-logos>,
and edit to square e.g. via <https://boxy-svg.com>.
"""

from ..lookup import countries
from ..tables import Vendor

aws = Vendor(
    vendor_id="aws",
    name="Amazon Web Services",
    logo="https://sc-data-public-40e9d310.s3.amazonaws.com/cdn/logos/aws.svg",
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
    logo="https://sc-data-public-40e9d310.s3.amazonaws.com/cdn/logos/gcp.svg",
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

hcloud = Vendor(
    vendor_id="hcloud",
    name="Hetzner Cloud",
    logo="https://sc-data-public-40e9d310.s3.amazonaws.com/cdn/logos/hcloud.svg",
    homepage="https://www.hetzner.com/cloud/",
    country=countries["DE"],
    state="Bavaria",
    city="Gunzenhausen",
    address_line="Industriestr. 25",
    zip_code="91710",
    founding_year=1997,
    status_page="https://status.hetzner.com/",
)
"""Hetzner Cloud."""
