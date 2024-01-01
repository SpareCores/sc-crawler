from .. import Location, Vendor
from ..compliance_frameworks import hipaa, soc2t2

aws = Vendor(
    id="aws",
    name="Amazon Web Services",
    homepage="https://aws.amazon.com",
    location=Location(country="US", city="Seattle", address_line1="410 Terry Ave N"),
    founding_year=2002,
    compliance_frameworks=[hipaa, soc2t2],
    status_page="https://health.aws.amazon.com/health/status",
)

gcp = Vendor(
    id="gcp",
    name="Google Cloud Platform",
    homepage="https://cloud.google.com",
    location=Location(
        country="US", city="Mountain View", address_line1="1600 Amphitheatre Pkwy"
    ),
    founding_year=2008,
    compliance_frameworks=[hipaa, soc2t2],
    status_page="https://status.cloud.google.com/",
)
