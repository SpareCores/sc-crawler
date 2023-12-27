import boto3

from .. import Location
from ..schemas import Datacenter


def get_datacenters(vendor, *args, **kwargs):
    datacenters = [
        Datacenter(
            identifier="af-south-1",
            name="Africa (Cape Town)",
            vendor=vendor,
            location=Location(country="ZA", city="Cape Town"),
        ),
        Datacenter(
            identifier="ap-east-1",
            name="Asia Pacific (Hong Kong)",
            vendor=vendor,
            location=Location(country="HK", city="Hong Kong"),
        ),
        Datacenter(
            identifier="ap-northeast-1",
            name="Asia Pacific (Tokyo)",
            vendor=vendor,
            location=Location(country="JP", city="Tokyo"),
        ),
        Datacenter(
            identifier="ap-northeast-2",
            name="Asia Pacific (Seoul)",
            vendor=vendor,
            location=Location(country="KR", city="Seoul"),
        ),
        Datacenter(
            identifier="ap-northeast-3",
            name="Asia Pacific (Osaka)",
            vendor=vendor,
            location=Location(country="JP", city="Osaka"),
        ),
        Datacenter(
            identifier="ap-south-1",
            name="Asia Pacific (Mumbai)",
            vendor=vendor,
            location=Location(country="IN", city="Mumbai"),
        ),
        Datacenter(
            identifier="ap-south-2",
            name="Asia Pacific (Hyderabad)",
            vendor=vendor,
            location=Location(country="IN", city="Hyderabad"),
        ),
        Datacenter(
            identifier="ap-southeast-1",
            name="Asia Pacific (Singapore)",
            vendor=vendor,
            location=Location(country="SG", city="Singapore"),
        ),
        Datacenter(
            identifier="ap-southeast-2",
            name="Asia Pacific (Sydney)",
            vendor=vendor,
            location=Location(country="AU", city="Sydney"),
        ),
        Datacenter(
            identifier="ap-southeast-3",
            name="Asia Pacific (Jakarta)",
            vendor=vendor,
            location=Location(country="ID", city="Jakarta"),
        ),
        Datacenter(
            identifier="ap-southeast-4",
            name="Asia Pacific (Melbourne)",
            vendor=vendor,
            location=Location(country="AU", city="Melbourne"),
        ),
        Datacenter(
            identifier="ca-central-1",
            name="Canada (Central)",
            vendor=vendor,
            location=Location(country="CA", city="Quebec"),  # NOTE needs city name
        ),
        Datacenter(
            identifier="ca-west-1",
            name="Canada West (Calgary)",
            vendor=vendor,
            location=Location(country="CA", city="Calgary"),
        ),
        Datacenter(
            identifier="cn-north-1",
            name="China (Beijing)",
            vendor=vendor,
            location=Location(country="CN", city="Beijing"),
        ),
        Datacenter(
            identifier="cn-northwest-1",
            name="China (Ningxia)",
            vendor=vendor,
            location=Location(country="CN", city="Ningxia"),  # NOTE needs city name
        ),
        Datacenter(
            identifier="eu-central-1",
            name="Europe (Frankfurt)",
            vendor=vendor,
            location=Location(country="DE", city="Frankfurt"),
        ),
        Datacenter(
            identifier="eu-central-2",
            name="Europe (Zurich)",
            vendor=vendor,
            location=Location(country="CH", city="Zurich"),
        ),
        Datacenter(
            identifier="eu-north-1",
            name="Europe (Stockholm)",
            vendor=vendor,
            location=Location(country="SE", city="Stockholm"),
        ),
        Datacenter(
            identifier="eu-south-1",
            name="Europe (Milan)",
            vendor=vendor,
            location=Location(country="IT", city="Milan"),
        ),
        Datacenter(
            identifier="eu-south-2",
            name="Europe (Spain)",
            vendor=vendor,
            location=Location(country="ES", city="Aragón"),  # NOTE needs city name
        ),
        Datacenter(
            identifier="eu-west-1",
            name="Europe (Ireland)",
            vendor=vendor,
            location=Location(country="IE", city="Dublin"),
        ),
        Datacenter(
            identifier="eu-west-2",
            name="Europe (London)",
            vendor=vendor,
            location=Location(country="GB", city="London"),
        ),
        Datacenter(
            identifier="eu-west-3",
            name="Europe (Paris)",
            vendor=vendor,
            location=Location(country="FR", city="Paris"),
        ),
        Datacenter(
            identifier="il-central-1",
            name="Israel (Tel Aviv)",
            vendor=vendor,
            location=Location(country="IL", city="Tel Aviv"),
        ),
        Datacenter(
            identifier="me-central-1",
            name="Middle East (UAE)",
            vendor=vendor,
            location=Location(country="AE"),  # NOTE city unknown
        ),
        Datacenter(
            identifier="me-central-2",
            name="Middle East (Bahrain)",
            vendor=vendor,
            location=Location(country="BH"),  # NOTE city unknown
        ),
        Datacenter(
            identifier="sa-east-1",
            name="South America (Sao Paulo)",
            vendor=vendor,
            location=Location(country="BR", city="Sao Paulo"),
        ),
        Datacenter(
            identifier="us-east-1",
            name="US East (N. Virginia)",
            vendor=vendor,
            location=Location(country="US", state="North Virgina"),  # NOTE city unknown
        ),
        Datacenter(
            identifier="us-east-2",
            name="US East (Ohio)",
            vendor=vendor,
            location=Location(country="US", state="Ohio"),  # NOTE city unknown
        ),
        Datacenter(
            identifier="us-west-1",
            name="US West (N. California)",
            vendor=vendor,
            location=Location(country="US", state="California"),  # NOTE city unknown
        ),
        Datacenter(
            identifier="us-west-2",
            name="US West (Oregon)",
            vendor=vendor,
            location=Location(country="US", state="Oregon"),  # NOTE city unknown
        ),
    ]

    # check if documented
    supported_regions = [d.identifier for d in datacenters]
    ec2 = boto3.client("ec2")
    regions = ec2.describe_regions().get("Regions", [])
    for region in regions:
        region_name = region.get("RegionName")
        if "gov" in region_name:
            next()
        if region_name not in supported_regions:
            raise NotImplementedError(
                f"Unsupported AWS datacenter: {region_name}")

    return datacenters


def get_instance_types(*args, **kwargs):
    return []
