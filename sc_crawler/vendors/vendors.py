from ..schemas import Vendor
from ..lookup import countries, compliance_frameworks


def get_compliance_frameworks(framework_ids):
    return [v for k, v in compliance_frameworks.items() if k in framework_ids]


aws = Vendor(
    id="aws",
    name="Amazon Web Services",
    homepage="https://aws.amazon.com",
    country=countries["US"],
    state="Washington",
    city="Seattle",
    address_line="410 Terry Ave N",
    zip_code="98109",
    founding_year=2002,
    compliance_frameworks=get_compliance_frameworks(["hipaa", "soc2t2"]),
    status_page="https://health.aws.amazon.com/health/status",
)

gcp = Vendor(
    id="gcp",
    name="Google Cloud Platform",
    homepage="https://cloud.google.com",
    country=countries["US"],
    state="California",
    city="Mountain View",
    address_line="1600 Amphitheatre Pkwy",
    zip_code="94043",
    founding_year=2008,
    compliance_frameworks=get_compliance_frameworks(["hipaa", "soc2t2"]),
    status_page="https://status.cloud.google.com/",
)
