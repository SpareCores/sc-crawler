"""Supported cloud and VPS provider vendors.

For logos, see e.g. <https://iconduck.com/sets/svg-logos>,
and edit to square e.g. via <https://boxy-svg.com>.
"""

from ..lookup import countries
from ..tables import Vendor

aws = Vendor(
    vendor_id="aws",
    name="Amazon Web Services",
    logo="https://sparecores.com/assets/images/vendors/aws.svg",
    homepage="https://aws.amazon.com",
    country=countries["US"],
    state="Washington",
    city="Seattle",
    address_line="410 Terry Ave N",
    zip_code="98109",
    founding_year=2002,
    status_page="https://health.aws.amazon.com/health/status",
    stopped_server_charged=False,
    billing_increment_seconds=1,
    minimum_billing_seconds=60,
)
"""Amazon Web Services."""

gcp = Vendor(
    vendor_id="gcp",
    name="Google Cloud Platform",
    logo="https://sparecores.com/assets/images/vendors/gcp.svg",
    homepage="https://cloud.google.com",
    country=countries["US"],
    state="California",
    city="Mountain View",
    address_line="1600 Amphitheatre Pkwy",
    zip_code="94043",
    founding_year=2008,
    status_page="https://status.cloud.google.com/",
    stopped_server_charged=False,
    billing_increment_seconds=1,
    minimum_billing_seconds=60,
)
"""Google Cloud Platform."""

hcloud = Vendor(
    vendor_id="hcloud",
    name="Hetzner Cloud",
    logo="https://sparecores.com/assets/images/vendors/hcloud.svg",
    homepage="https://www.hetzner.com/cloud/",
    country=countries["DE"],
    state="Bavaria",
    city="Gunzenhausen",
    address_line="Industriestr. 25",
    zip_code="91710",
    founding_year=2018,
    status_page="https://status.hetzner.com/",
    stopped_server_charged=True,
    billing_increment_seconds=3600,
    minimum_billing_seconds=3600,
)
"""Hetzner Cloud."""

azure = Vendor(
    vendor_id="azure",
    name="Microsoft Azure",
    logo="https://sparecores.com/assets/images/vendors/azure.svg",
    homepage="https://azure.microsoft.com",
    country=countries["US"],
    state="Washington",
    city="Redmond",
    address_line="One Microsoft Way",
    zip_code="98052",
    founding_year=2010,
    status_page="https://azure.status.microsoft.com",
    stopped_server_charged=True,
    billing_increment_seconds=1,
    minimum_billing_seconds=300,
    billing_comment="Billing of stopped server depends on allocation status.",
)
"""Microsoft Azure."""

upcloud = Vendor(
    vendor_id="upcloud",
    name="UpCloud",
    logo="https://sparecores.com/assets/images/vendors/upcloud.svg",
    homepage="https://upcloud.com",
    country=countries["FI"],
    state="Uusimaa",
    city="Helsinki",
    address_line="Aleksanterinkatu 15 B, 7th floor",
    zip_code="00100",
    founding_year=2012,
    status_page="https://status.upcloud.com",
    stopped_server_charged=True,
    billing_increment_seconds=3600,
    minimum_billing_seconds=3600,
    billing_comment="Developer and General Purpose bill while stopped; Cloud Native only when powered on.",
)
"""UpCloud."""

alicloud = Vendor(
    vendor_id="alicloud",
    name="Alibaba Cloud",
    logo="https://sparecores.com/assets/images/vendors/alicloud.svg",
    homepage="https://www.alibabacloud.com/",
    country=countries["CN"],
    state="Zhejiang",
    city="Hangzhou",
    address_line="969 West Wen Yi Road",
    zip_code="311121",
    founding_year=2009,
    status_page="https://status.alibabacloud.com/",
    stopped_server_charged=True,
    billing_increment_seconds=1,
    minimum_billing_seconds=600,
    billing_comment="Billing of stopped server depends on Standard or Economical plan. Min billing 600, 300, or 120 seconds by vCPU.",
)
"""Alibaba Cloud."""

ovh = Vendor(
    vendor_id="ovh",
    name="OVHcloud",
    logo="https://sparecores.com/assets/images/vendors/ovh.svg",
    homepage="https://www.ovhcloud.com",
    country=countries["FR"],
    state="Hauts-de-France",
    city="Roubaix",
    address_line="2 rue Kellermann",
    zip_code="59100",
    founding_year=1999,
    status_page="https://www.status-ovhcloud.com",
    stopped_server_charged=False,
    billing_increment_seconds=3600,
    minimum_billing_seconds=3600,
    billing_comment="Billing for stopped servers depends on status: shelved, snapshots only; suspended or paused, billed like running.",
)
"""OVHcloud."""
