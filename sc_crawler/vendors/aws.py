import boto3

from .. import Location
from ..schemas import Datacenter


def get_datacenters(vendor, *args, **kwargs):
    # launch date: https://aws.amazon.com/about-aws/global-infrastructure/regions_az/
    datacenters = [
        Datacenter(
            identifier="af-south-1",
            name="Africa (Cape Town)",
            vendor=vendor,
            location=Location(country="ZA", city="Cape Town"),
            founding_year=2020,
        ),
        Datacenter(
            identifier="ap-east-1",
            name="Asia Pacific (Hong Kong)",
            vendor=vendor,
            location=Location(country="HK", city="Hong Kong"),
            founding_year=2019,
        ),
        Datacenter(
            identifier="ap-northeast-1",
            name="Asia Pacific (Tokyo)",
            vendor=vendor,
            location=Location(country="JP", city="Tokyo"),
            founding_year=2011,
        ),
        Datacenter(
            identifier="ap-northeast-2",
            name="Asia Pacific (Seoul)",
            vendor=vendor,
            location=Location(country="KR", city="Seoul"),
            founding_year=2016,
        ),
        Datacenter(
            identifier="ap-northeast-3",
            name="Asia Pacific (Osaka)",
            vendor=vendor,
            location=Location(country="JP", city="Osaka"),
            founding_year=2021,
        ),
        Datacenter(
            identifier="ap-south-1",
            name="Asia Pacific (Mumbai)",
            vendor=vendor,
            location=Location(country="IN", city="Mumbai"),
            founding_year=2016,
        ),
        Datacenter(
            identifier="ap-south-2",
            name="Asia Pacific (Hyderabad)",
            vendor=vendor,
            location=Location(country="IN", city="Hyderabad"),
            founding_year=2022,
        ),
        Datacenter(
            identifier="ap-southeast-1",
            name="Asia Pacific (Singapore)",
            vendor=vendor,
            location=Location(country="SG", city="Singapore"),
            founding_year=2010,
        ),
        Datacenter(
            identifier="ap-southeast-2",
            name="Asia Pacific (Sydney)",
            vendor=vendor,
            location=Location(country="AU", city="Sydney"),
            founding_year=2012,
        ),
        Datacenter(
            identifier="ap-southeast-3",
            name="Asia Pacific (Jakarta)",
            vendor=vendor,
            location=Location(country="ID", city="Jakarta"),
            founding_year=2021,
        ),
        Datacenter(
            identifier="ap-southeast-4",
            name="Asia Pacific (Melbourne)",
            vendor=vendor,
            location=Location(country="AU", city="Melbourne"),
            founding_year=2023,
        ),
        Datacenter(
            identifier="ca-central-1",
            name="Canada (Central)",
            vendor=vendor,
            location=Location(country="CA", city="Quebec"),  # NOTE needs city name
            founding_year=2016,
        ),
        Datacenter(
            identifier="ca-west-1",
            name="Canada West (Calgary)",
            vendor=vendor,
            location=Location(country="CA", city="Calgary"),
            founding_year=2023,
        ),
        Datacenter(
            identifier="cn-north-1",
            name="China (Beijing)",
            vendor=vendor,
            location=Location(country="CN", city="Beijing"),
            founding_year=2016,
        ),
        Datacenter(
            identifier="cn-northwest-1",
            name="China (Ningxia)",
            vendor=vendor,
            location=Location(country="CN", city="Ningxia"),  # NOTE needs city name
            founding_year=2017,
        ),
        Datacenter(
            identifier="eu-central-1",
            name="Europe (Frankfurt)",
            vendor=vendor,
            location=Location(country="DE", city="Frankfurt"),
            founding_year=2014,
        ),
        Datacenter(
            identifier="eu-central-2",
            name="Europe (Zurich)",
            vendor=vendor,
            location=Location(country="CH", city="Zurich"),
            founding_year=2022,
        ),
        Datacenter(
            identifier="eu-north-1",
            name="Europe (Stockholm)",
            vendor=vendor,
            location=Location(country="SE", city="Stockholm"),
            founding_year=2018,
        ),
        Datacenter(
            identifier="eu-south-1",
            name="Europe (Milan)",
            vendor=vendor,
            location=Location(country="IT", city="Milan"),
            founding_year=2020,
        ),
        Datacenter(
            identifier="eu-south-2",
            name="Europe (Spain)",
            vendor=vendor,
            location=Location(country="ES", city="Aragón"),  # NOTE needs city name
            founding_year=2022,
        ),
        Datacenter(
            identifier="eu-west-1",
            name="Europe (Ireland)",
            vendor=vendor,
            location=Location(country="IE", city="Dublin"),
            founding_year=2007,
        ),
        Datacenter(
            identifier="eu-west-2",
            name="Europe (London)",
            vendor=vendor,
            location=Location(country="GB", city="London"),
            founding_year=2016,
        ),
        Datacenter(
            identifier="eu-west-3",
            name="Europe (Paris)",
            vendor=vendor,
            location=Location(country="FR", city="Paris"),
            founding_year=2017,
        ),
        Datacenter(
            identifier="il-central-1",
            name="Israel (Tel Aviv)",
            vendor=vendor,
            location=Location(country="IL", city="Tel Aviv"),
            founding_year=2023,
        ),
        Datacenter(
            identifier="me-central-1",
            name="Middle East (UAE)",
            vendor=vendor,
            location=Location(country="AE"),  # NOTE city unknown
            founding_year=2022,
        ),
        Datacenter(
            identifier="me-central-2",
            name="Middle East (Bahrain)",
            vendor=vendor,
            location=Location(country="BH"),  # NOTE city unknown
            founding_year=2019,
        ),
        Datacenter(
            identifier="sa-east-1",
            name="South America (Sao Paulo)",
            vendor=vendor,
            location=Location(country="BR", city="Sao Paulo"),
            founding_year=2011,
        ),
        Datacenter(
            identifier="us-east-1",
            name="US East (N. Virginia)",
            vendor=vendor,
            location=Location(
                country="US", state="Northern Virgina"
            ),  # NOTE city unknown
            founding_year=2006,
        ),
        Datacenter(
            identifier="us-east-2",
            name="US East (Ohio)",
            vendor=vendor,
            location=Location(country="US", state="Ohio"),  # NOTE city unknown
            founding_year=2016,
        ),
        Datacenter(
            identifier="us-west-1",
            name="US West (N. California)",
            vendor=vendor,
            location=Location(country="US", state="California"),  # NOTE city unknown
            founding_year=2009,
        ),
        Datacenter(
            identifier="us-west-2",
            name="US West (Oregon)",
            vendor=vendor,
            location=Location(country="US", state="Oregon"),  # NOTE city unknown
            founding_year=2011,
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
            raise NotImplementedError(f"Unsupported AWS datacenter: {region_name}")

    return datacenters


def get_instance_types(*args, **kwargs):
    return []
