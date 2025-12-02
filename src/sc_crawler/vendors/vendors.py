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
    founding_year=1997,
    status_page="https://status.hetzner.com/",
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
    founding_year=2008,
    status_page="https://azure.status.microsoft.com",
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
)
"""UpCloud."""

aliyun = Vendor(
    vendor_id="aliyun",
    name="Alibaba Cloud",
    logo="https://sparecores.com/assets/images/vendors/aliyun.svg",
    homepage="https://www.alibabacloud.com/",
    country=countries["CN"],
    state="Zhejiang",
    city="Hangzhou",
    address_line="5F, Builing D, the West Lake International Plaza of S&T No.391 Wen'er Road",
    zip_code="310099",
    founding_year=2009,
    status_page="https://status.alibabacloud.com/",
)
"""Alibaba Cloud / Aliyun."""