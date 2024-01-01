import boto3
from cachier import cachier, set_default_params
from datetime import timedelta
from itertools import chain
import logging
import re

from .. import Location
from ..schemas import Datacenter  # , Zone, Server, Storage, Gpu

logger = logging.getLogger(__name__)

# disable caching by default
set_default_params(caching_enabled=False)

# ##############################################################################
# AWS cached helpers


@cachier(stale_after=timedelta(days=3))
def describe_instance_types(region):
    ec2 = boto3.client("ec2", region_name=region)
    return ec2.describe_instance_types()["InstanceTypes"]


@cachier(stale_after=timedelta(days=3))
def describe_regions():
    ec2 = boto3.client("ec2")
    return ec2.describe_regions().get("Regions", [])


@cachier(stale_after=timedelta(days=3))
def describe_availability_zones(region):
    ec2 = boto3.client("ec2", region_name=region)
    zones = ec2.describe_availability_zones(
        Filters=[
            {"Name": "zone-type", "Values": ["availability-zone"]},
        ],
        AllAvailabilityZones=True,
    )["AvailabilityZones"]
    return zones


# ##############################################################################


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
    regions = describe_regions()
    for region in regions:
        region_name = region["RegionName"]
        if "gov" in region_name:
            next()
        if region_name not in supported_regions:
            raise NotImplementedError(f"Unsupported AWS datacenter: {region_name}")

    # filter for datacenters enabled for the account
    datacenters = [
        datacenter
        for datacenter in datacenters
        if datacenter.identifier in [region["RegionName"] for region in regions]
    ]

    # make it easier to access by region name
    # datacenters = {datacenter.identifier: datacenter for datacenter in datacenters}

    # add zones
    for datacenter in datacenters:
        zones = describe_availability_zones(datacenter.identifier)
        datacenter._zones = {
            zone["ZoneId"]: Zone(
                identifier=zone["ZoneId"],
                name=zone["ZoneName"],
                datacenter=datacenter,
            )
            for zone in zones
        }

    return datacenters


instance_families = {
    "c": "Compute optimized",
    "d": "Dense storage",
    "f": "FPGA",
    "g": "Graphics intensive",
    "hpc": "High performance computing",
    "i": "Storage optimized",
    "im": "Storage optimized with a one to four ratio of vCPU to memory",
    "is": "Storage optimized with a one to six ratio of vCPU to memory",
    "inf": "AWS Inferentia",
    "m": "General purpose",
    "mac": "macOS",
    "p": "GPU accelerated",
    "r": "Memory optimized",
    "t": "Burstable performance",
    "trn": "AWS Trainium",
    "u": "High memory",
    "vt": "Video transcoding",
    "x": "Memory intensive",
    "z": "High frequency",
}

instance_suffixes = {
    # Processor families
    "a": "AMD processors",
    "g": "AWS Graviton processors",
    "i": "Intel processors",
    # Additional capabilities
    "d": "Instance store volumes",
    "n": "Network and EBS optimized",
    "e": "Extra storage or memory",
    "z": "High performance",
    "q": "Qualcomm inference accelerators",
    "flex": "Flex instance",
}


def annotate_instance_type(instance_type_id):
    """Resolve instance type coding to human-friendly description.

    Source: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-types.html#instance-type-names
    """  # noqa: E501
    kind = instance_type_id.split(".")[0]
    # drop suffixes for now after the dash, e.g. "Mac2-m2", "Mac2-m2pro"
    if "-" in kind:
        logger.warning(f"Truncating instance type after the dash: {kind}")
    kind = kind.split("-")[0]
    family, extras = re.split(r"[0-9]", kind)
    generation = re.findall(r"[0-9]", kind)[0]
    size = instance_type_id.split(".")[1]

    text = instance_families[family]
    for k, v in instance_suffixes.items():
        if k in extras:
            text += " [" + v + "]"
    text += " Gen" + generation
    text += " " + size

    return text


def get_storage(instance_type, nvme=False):
    """Get overall storage size and type (tupple) from instance details."""
    if "InstanceStorageInfo" not in instance_type:
        return (0, None)
    info = instance_type["InstanceStorageInfo"]
    storage_size = info["TotalSizeInGB"]
    storage_type = info["Disks"][0].get("Type").lower()
    if storage_type == "ssd" and info.get("NvmeSupport", False):
        storage_type = "nvme ssd"
    return (storage_size, storage_type)


def array_expand_by_count(array):
    """Expand an array with its items Count field."""
    array = [[a] * a["Count"] for a in array]
    return list(chain(*array))


def get_storages(instance_type):
    """Get individual storages as an array."""
    if "InstanceStorageInfo" not in instance_type:
        return []
    info = instance_type["InstanceStorageInfo"]

    def to_storage(disk, nvme=False):
        kind = disk.get("Type").lower()
        if kind == "ssd" and nvme:
            kind = "nvme ssd"
        return Storage(size=disk["SizeInGB"], storage_type=kind)

    # replicate number of disks
    disks = info["Disks"]
    disks = array_expand_by_count(disks)
    return [to_storage(disk, nvme=info.get("NvmeSupport", False)) for disk in disks]


def get_gpu(instance_type):
    """Get overall GPU count, memory and manufacturer/name."""
    if "GpuInfo" not in instance_type:
        return (0, None, None)
    info = instance_type["GpuInfo"]
    memory = info["TotalGpuMemoryInMiB"]

    def mn(gpu):
        return gpu["Manufacturer"] + " " + gpu["Name"]

    # iterate over each GPU
    count = sum([gpu["Count"] for gpu in info["Gpus"]])
    names = ", ".join([mn(gpu) for gpu in info["Gpus"]])
    return (count, memory, names)


def get_gpus(instance_type):
    """Get individual GPUs as an array."""
    if "GpuInfo" not in instance_type:
        return []
    info = instance_type["GpuInfo"]

    def to_gpu(gpu):
        return Gpu(
            manufacturer=gpu["Manufacturer"],
            name=gpu["Name"],
            memory=gpu["MemoryInfo"]["SizeInMiB"],
        )

    # replicate number of disks
    gpus = info["Gpus"]
    gpus = array_expand_by_count(gpus)
    return [to_gpu(gpu) for gpu in gpus]


def get_instance_types(vendor, *args, **kwargs):
    if not hasattr(vendor, "_datacenters"):
        raise AttributeError("Datacenters not defined, run get_datacenters()")
    regions = [datacenter.identifier for datacenter in vendor._datacenters]
    instance_types = {}
    # might be instance types specific to a few or even a single region
    for region in regions:
        logger.debug(f"Looking up instance types in region {region}")
        local_instance_types = describe_instance_types(region)
        for instance_type in local_instance_types:
            it = instance_type["InstanceType"]
            if it not in list(instance_types.keys()):
                vcpu_info = instance_type["VCpuInfo"]
                cpu_info = instance_type["ProcessorInfo"]
                gpu_info = get_gpu(instance_type)
                storage_info = get_storage(instance_type)
                network_card = instance_type["NetworkInfo"]["NetworkCards"][0]
                instance_types.update(
                    {
                        it: Server(
                            identifier=it,
                            name=it,
                            description=annotate_instance_type(it),
                            vcpus=vcpu_info["DefaultVCpus"],
                            cpu_cores=vcpu_info["DefaultCores"],
                            cpu_speed=cpu_info.get("SustainedClockSpeedInGhz", None),
                            cpu_architecture=cpu_info["SupportedArchitectures"][0],
                            cpu_manufacturer=cpu_info.get("Manufacturer", None),
                            memory=instance_type["MemoryInfo"]["SizeInMiB"],
                            gpu_count=gpu_info[0],
                            gpu_memory=gpu_info[1],
                            gpu_name=gpu_info[2],
                            gpus=get_gpus(instance_type),
                            storage_size=storage_info[0],
                            storage_type=storage_info[1],
                            storages=get_storages(instance_type),
                            network_speed=network_card["BaselineBandwidthInGbps"],
                            billable_unit="hour",
                        )
                    }
                )

    return instance_types
