# import boto3

from .. import Location
from ..schemas import Datacenter


def get_datacenters(vendor, *args, **kwargs):
    # ec2 = boto3.client('ec2')
    # regions = ec2.describe_regions().get('Regions',[] )
    datacenters = [
        Datacenter(
            identifier="af-south-1",
            name="Africa (Cape Town)",
            vendor=vendor,
            location=Location(country="US", city="Cape Town"),
        )
    ]
    return datacenters


def get_instance_types(*args, **kwargs):
    return []
