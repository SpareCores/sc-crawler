from ..lookup import compliance_frameworks, countries
from ..schemas import Vendor, VendorComplianceLink


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
    status_page="https://health.aws.amazon.com/health/status",
)

for cf in ["hipaa", "soc2t2"]:
    VendorComplianceLink(vendor=aws, compliance_framework=compliance_frameworks[cf])

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
    status_page="https://status.cloud.google.com/",
)

for cf in ["hipaa", "soc2t2"]:
    VendorComplianceLink(vendor=gcp, compliance_framework=compliance_frameworks[cf])
