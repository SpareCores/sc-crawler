import boto3

from .. import Location
from ..schemas import Datacenter, Zone


def get_datacenters(vendor, *args, **kwargs):
    """List all available AWS datacenters.

    Some data sources are not available from APIs, and were collected manually:
    - launch date: https://aws.amazon.com/about-aws/global-infrastructure/regions_az/
    - energy source: https://sustainability.aboutamazon.com/products-services/the-cloud?energyType=true#renewable-energy
    """  # noqa: E501
    datacenters = [
        Datacenter(
            identifier="af-south-1",
            name="Africa (Cape Town)",
            vendor=vendor,
            location=Location(country="ZA", city="Cape Town"),
            founding_year=2020,
            green_energy=False,
        ),
        Datacenter(
            identifier="ap-east-1",
            name="Asia Pacific (Hong Kong)",
            vendor=vendor,
            location=Location(country="HK", city="Hong Kong"),
            founding_year=2019,
            green_energy=False,
        ),
        Datacenter(
            identifier="ap-northeast-1",
            name="Asia Pacific (Tokyo)",
            vendor=vendor,
            location=Location(country="JP", city="Tokyo"),
            founding_year=2011,
            green_energy=False,
        ),
        Datacenter(
            identifier="ap-northeast-2",
            name="Asia Pacific (Seoul)",
            vendor=vendor,
            location=Location(country="KR", city="Seoul"),
            founding_year=2016,
            green_energy=False,
        ),
        Datacenter(
            identifier="ap-northeast-3",
            name="Asia Pacific (Osaka)",
            vendor=vendor,
            location=Location(country="JP", city="Osaka"),
            founding_year=2021,
            green_energy=False,
        ),
        Datacenter(
            identifier="ap-south-1",
            name="Asia Pacific (Mumbai)",
            vendor=vendor,
            location=Location(country="IN", city="Mumbai"),
            founding_year=2016,
            green_energy=True,
        ),
        Datacenter(
            identifier="ap-south-2",
            name="Asia Pacific (Hyderabad)",
            vendor=vendor,
            location=Location(country="IN", city="Hyderabad"),
            founding_year=2022,
            green_energy=True,
        ),
        Datacenter(
            identifier="ap-southeast-1",
            name="Asia Pacific (Singapore)",
            vendor=vendor,
            location=Location(country="SG", city="Singapore"),
            founding_year=2010,
            green_energy=False,
        ),
        Datacenter(
            identifier="ap-southeast-2",
            name="Asia Pacific (Sydney)",
            vendor=vendor,
            location=Location(country="AU", city="Sydney"),
            founding_year=2012,
            green_energy=False,
        ),
        Datacenter(
            identifier="ap-southeast-3",
            name="Asia Pacific (Jakarta)",
            vendor=vendor,
            location=Location(country="ID", city="Jakarta"),
            founding_year=2021,
            green_energy=False,
        ),
        Datacenter(
            identifier="ap-southeast-4",
            name="Asia Pacific (Melbourne)",
            vendor=vendor,
            location=Location(country="AU", city="Melbourne"),
            founding_year=2023,
            green_energy=False,
        ),
        Datacenter(
            identifier="ca-central-1",
            name="Canada (Central)",
            vendor=vendor,
            location=Location(country="CA", city="Quebec"),  # NOTE needs city name
            founding_year=2016,
            green_energy=True,
        ),
        Datacenter(
            identifier="ca-west-1",
            name="Canada West (Calgary)",
            vendor=vendor,
            location=Location(country="CA", city="Calgary"),
            founding_year=2023,
            green_energy=False,
        ),
        Datacenter(
            identifier="cn-north-1",
            name="China (Beijing)",
            vendor=vendor,
            location=Location(country="CN", city="Beijing"),
            founding_year=2016,
            green_energy=True,
        ),
        Datacenter(
            identifier="cn-northwest-1",
            name="China (Ningxia)",
            vendor=vendor,
            location=Location(country="CN", city="Ningxia"),  # NOTE needs city name
            founding_year=2017,
            green_energy=True,
        ),
        Datacenter(
            identifier="eu-central-1",
            name="Europe (Frankfurt)",
            vendor=vendor,
            location=Location(country="DE", city="Frankfurt"),
            founding_year=2014,
            green_energy=True,
        ),
        Datacenter(
            identifier="eu-central-2",
            name="Europe (Zurich)",
            vendor=vendor,
            location=Location(country="CH", city="Zurich"),
            founding_year=2022,
            green_energy=True,
        ),
        Datacenter(
            identifier="eu-north-1",
            name="Europe (Stockholm)",
            vendor=vendor,
            location=Location(country="SE", city="Stockholm"),
            founding_year=2018,
            green_energy=True,
        ),
        Datacenter(
            identifier="eu-south-1",
            name="Europe (Milan)",
            vendor=vendor,
            location=Location(country="IT", city="Milan"),
            founding_year=2020,
            green_energy=True,
        ),
        Datacenter(
            identifier="eu-south-2",
            name="Europe (Spain)",
            vendor=vendor,
            location=Location(country="ES", city="Aragón"),  # NOTE needs city name
            founding_year=2022,
            green_energy=True,
        ),
        Datacenter(
            identifier="eu-west-1",
            name="Europe (Ireland)",
            vendor=vendor,
            location=Location(country="IE", city="Dublin"),
            founding_year=2007,
            green_energy=True,
        ),
        Datacenter(
            identifier="eu-west-2",
            name="Europe (London)",
            vendor=vendor,
            location=Location(country="GB", city="London"),
            founding_year=2016,
            green_energy=True,
        ),
        Datacenter(
            identifier="eu-west-3",
            name="Europe (Paris)",
            vendor=vendor,
            location=Location(country="FR", city="Paris"),
            founding_year=2017,
            green_energy=True,
        ),
        Datacenter(
            identifier="il-central-1",
            name="Israel (Tel Aviv)",
            vendor=vendor,
            location=Location(country="IL", city="Tel Aviv"),
            founding_year=2023,
            green_energy=False,
        ),
        Datacenter(
            identifier="me-central-1",
            name="Middle East (UAE)",
            vendor=vendor,
            location=Location(country="AE"),  # NOTE city unknown
            founding_year=2022,
            green_energy=False,
        ),
        Datacenter(
            identifier="me-central-2",
            name="Middle East (Bahrain)",
            vendor=vendor,
            location=Location(country="BH"),  # NOTE city unknown
            founding_year=2019,
            green_energy=False,
        ),
        Datacenter(
            identifier="sa-east-1",
            name="South America (Sao Paulo)",
            vendor=vendor,
            location=Location(country="BR", city="Sao Paulo"),
            founding_year=2011,
            green_energy=False,
        ),
        Datacenter(
            identifier="us-east-1",
            name="US East (N. Virginia)",
            vendor=vendor,
            location=Location(
                country="US", state="Northern Virgina"
            ),  # NOTE city unknown
            founding_year=2006,
            green_energy=True,
        ),
        Datacenter(
            identifier="us-east-2",
            name="US East (Ohio)",
            vendor=vendor,
            location=Location(country="US", state="Ohio"),  # NOTE city unknown
            founding_year=2016,
            green_energy=True,
        ),
        Datacenter(
            identifier="us-west-1",
            name="US West (N. California)",
            vendor=vendor,
            location=Location(country="US", state="California"),  # NOTE city unknown
            founding_year=2009,
            green_energy=True,
        ),
        Datacenter(
            identifier="us-west-2",
            name="US West (Oregon)",
            vendor=vendor,
            location=Location(country="US", state="Oregon"),  # NOTE city unknown
            founding_year=2011,
            green_energy=True,
        ),
    ]

    # look for undocumented (new) datacenters in AWS
    supported_regions = [d.identifier for d in datacenters]
    ec2 = boto3.client("ec2")
    regions = ec2.describe_regions().get("Regions", [])
    for region in regions:
        region_name = region.get("RegionName")
        if "gov" in region_name:
            next()
        if region_name not in supported_regions:
            raise NotImplementedError(f"Unsupported AWS datacenter: {region_name}")

    # filter for datacenters enabled for the account
    datacenters = [
        datacenter
        for datacenter in datacenters
        if datacenter.identifier in [region.get("RegionName") for region in regions]
    ]

    # make it easier to access by region name
    # datacenters = {datacenter.identifier: datacenter for datacenter in datacenters}

    # add zones
    for datacenter in datacenters:
        # need to create a new clien in each AWS region
        ec2 = boto3.client("ec2", region_name=datacenter.identifier)
        zones = ec2.describe_availability_zones(
            Filters=[
                {"Name": "zone-type", "Values": ["availability-zone"]},
            ],
            AllAvailabilityZones=True,
        ).get("AvailabilityZones")
        datacenter._zones = {
            zone.get("ZoneId"): Zone(
                identifier=zone.get("ZoneId"),
                name=zone.get("ZoneName"),
                datacenter=datacenter,
            )
            for zone in zones
        }

    return datacenters


def get_instance_types(*args, **kwargs):
    return []
