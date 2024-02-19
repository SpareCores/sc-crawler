import json
import re
from collections import ChainMap
from datetime import datetime, timedelta
from itertools import chain

import boto3
from cachier import cachier, set_default_params

from ..logger import logger
from ..lookup import countries
from ..schemas import Datacenter, Gpu, ServerPrice, Duration, Server, Disk, Zone

# disable caching by default
set_default_params(caching_enabled=False, stale_after=timedelta(days=1))

# ##############################################################################
# AWS cached helpers


@cachier()
def describe_instance_types(region):
    ec2 = boto3.client("ec2", region_name=region)
    pages = ec2.get_paginator("describe_instance_types")
    pages = pages.paginate().build_full_result()
    return pages["InstanceTypes"]


@cachier()
def describe_regions():
    ec2 = boto3.client("ec2")
    return ec2.describe_regions().get("Regions", [])


@cachier()
def describe_availability_zones(region):
    ec2 = boto3.client("ec2", region_name=region)
    zones = ec2.describe_availability_zones(
        Filters=[
            {"Name": "zone-type", "Values": ["availability-zone"]},
        ],
        AllAvailabilityZones=True,
    )["AvailabilityZones"]
    return zones


@cachier()
def get_price_list(region):
    """Download published AWS price lists. Currently unused."""
    # pricing API is only available in a few regions
    client = boto3.client("pricing", region_name="us-east-1")
    price_lists = client.list_price_lists(
        ServiceCode="AmazonEC2",
        EffectiveDate=datetime.now(),
        CurrencyCode="USD",
        RegionCode=region,
    )
    price_list_url = client.get_price_list_file_url(
        PriceListArn=price_lists["PriceLists"][0]["PriceListArn"], FileFormat="json"
    )
    return price_list_url


@cachier()
def get_products():
    # pricing API is only available in a few regions
    client = boto3.client("pricing", region_name="us-east-1")
    filters = {
        # TODO ingest win, mac etc others
        "operatingSystem": "Linux",
        "preInstalledSw": "NA",
        "licenseModel": "No License required",
        "locationType": "AWS Region",
        "capacitystatus": "Used",
        "marketoption": "OnDemand",
        # TODO dedicated options?
        "tenancy": "Shared",
    }
    filters = [
        {"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in filters.items()
    ]

    paginator = client.get_paginator("get_products")
    # return actual list instead of an iterator to be able to cache on disk
    products = []
    for page in paginator.paginate(ServiceCode="AmazonEC2", Filters=filters):
        for product_json in page["PriceList"]:
            product = json.loads(product_json)
            products.append(product)

    return products


# ##############################################################################


def get_datacenters(vendor, *args, **kwargs):
    """List all available AWS datacenters.

    Some data sources are not available from APIs, and were collected manually:
    - launch date: https://aws.amazon.com/about-aws/global-infrastructure/regions_az/
    - energy source: https://sustainability.aboutamazon.com/products-services/the-cloud?energyType=true#renewable-energy
    """  # noqa: E501
    datacenters = [
        Datacenter(
            id="af-south-1",
            name="Africa (Cape Town)",
            vendor=vendor,
            country=countries["ZA"],
            city="Cape Town",
            founding_year=2020,
            green_energy=False,
        ),
        Datacenter(
            id="ap-east-1",
            name="Asia Pacific (Hong Kong)",
            vendor=vendor,
            country=countries["HK"],
            city="Hong Kong",
            founding_year=2019,
            green_energy=False,
        ),
        Datacenter(
            id="ap-northeast-1",
            name="Asia Pacific (Tokyo)",
            vendor=vendor,
            country=countries["JP"],
            city="Tokyo",
            founding_year=2011,
            green_energy=False,
        ),
        Datacenter(
            id="ap-northeast-2",
            name="Asia Pacific (Seoul)",
            vendor=vendor,
            country=countries["KR"],
            city="Seoul",
            founding_year=2016,
            green_energy=False,
        ),
        Datacenter(
            id="ap-northeast-3",
            name="Asia Pacific (Osaka)",
            vendor=vendor,
            country=countries["JP"],
            city="Osaka",
            founding_year=2021,
            green_energy=False,
        ),
        Datacenter(
            id="ap-south-1",
            name="Asia Pacific (Mumbai)",
            vendor=vendor,
            country=countries["IN"],
            city="Mumbai",
            founding_year=2016,
            green_energy=True,
        ),
        Datacenter(
            id="ap-south-2",
            name="Asia Pacific (Hyderabad)",
            vendor=vendor,
            country=countries["IN"],
            city="Hyderabad",
            founding_year=2022,
            green_energy=True,
        ),
        Datacenter(
            id="ap-southeast-1",
            name="Asia Pacific (Singapore)",
            vendor=vendor,
            country=countries["SG"],
            city="Singapore",
            founding_year=2010,
            green_energy=False,
        ),
        Datacenter(
            id="ap-southeast-2",
            name="Asia Pacific (Sydney)",
            vendor=vendor,
            country=countries["AU"],
            city="Sydney",
            founding_year=2012,
            green_energy=False,
        ),
        Datacenter(
            id="ap-southeast-3",
            name="Asia Pacific (Jakarta)",
            vendor=vendor,
            country=countries["ID"],
            city="Jakarta",
            founding_year=2021,
            green_energy=False,
        ),
        Datacenter(
            id="ap-southeast-4",
            name="Asia Pacific (Melbourne)",
            vendor=vendor,
            country=countries["AU"],
            city="Melbourne",
            founding_year=2023,
            green_energy=False,
        ),
        Datacenter(
            id="ca-central-1",
            name="Canada (Central)",
            vendor=vendor,
            country=countries["CA"],
            city="Quebec",  # NOTE needs city name
            founding_year=2016,
            green_energy=True,
        ),
        Datacenter(
            id="ca-west-1",
            name="Canada West (Calgary)",
            vendor=vendor,
            country=countries["CA"],
            city="Calgary",
            founding_year=2023,
            green_energy=False,
        ),
        Datacenter(
            id="cn-north-1",
            name="China (Beijing)",
            vendor=vendor,
            country=countries["CN"],
            city="Beijing",
            founding_year=2016,
            green_energy=True,
        ),
        Datacenter(
            id="cn-northwest-1",
            name="China (Ningxia)",
            vendor=vendor,
            country=countries["CN"],
            city="Ningxia",  # NOTE needs city name
            founding_year=2017,
            green_energy=True,
        ),
        Datacenter(
            id="eu-central-1",
            name="Europe (Frankfurt)",
            aliases=["EU (Frankfurt)"],
            vendor=vendor,
            country=countries["DE"],
            city="Frankfurt",
            founding_year=2014,
            green_energy=True,
        ),
        Datacenter(
            id="eu-central-2",
            name="Europe (Zurich)",
            vendor=vendor,
            country=countries["CH"],
            city="Zurich",
            founding_year=2022,
            green_energy=True,
        ),
        Datacenter(
            id="eu-north-1",
            name="Europe (Stockholm)",
            aliases=["EU (Stockholm)"],
            vendor=vendor,
            country=countries["SE"],
            city="Stockholm",
            founding_year=2018,
            green_energy=True,
        ),
        Datacenter(
            id="eu-south-1",
            name="Europe (Milan)",
            aliases=["EU (Milan)"],
            vendor=vendor,
            country=countries["IT"],
            city="Milan",
            founding_year=2020,
            green_energy=True,
        ),
        Datacenter(
            id="eu-south-2",
            name="Europe (Spain)",
            vendor=vendor,
            country=countries["ES"],
            city="Aragón",  # NOTE needs city name
            founding_year=2022,
            green_energy=True,
        ),
        Datacenter(
            id="eu-west-1",
            name="Europe (Ireland)",
            aliases=["EU (Ireland)"],
            vendor=vendor,
            country=countries["IE"],
            city="Dublin",
            founding_year=2007,
            green_energy=True,
        ),
        Datacenter(
            id="eu-west-2",
            name="Europe (London)",
            aliases=["EU (London)"],
            vendor=vendor,
            country=countries["GB"],
            city="London",
            founding_year=2016,
            green_energy=True,
        ),
        Datacenter(
            id="eu-west-3",
            name="Europe (Paris)",
            aliases=["EU (Paris)"],
            vendor=vendor,
            country=countries["FR"],
            city="Paris",
            founding_year=2017,
            green_energy=True,
        ),
        Datacenter(
            id="il-central-1",
            name="Israel (Tel Aviv)",
            vendor=vendor,
            country=countries["IL"],
            city="Tel Aviv",
            founding_year=2023,
            green_energy=False,
        ),
        Datacenter(
            id="me-central-1",
            name="Middle East (UAE)",
            vendor=vendor,
            country=countries["AE"],
            # NOTE city unknown
            founding_year=2022,
            green_energy=False,
        ),
        Datacenter(
            id="me-central-2",
            name="Middle East (Bahrain)",
            vendor=vendor,
            country=countries["BH"],
            # NOTE city unknown
            founding_year=2019,
            green_energy=False,
        ),
        Datacenter(
            id="sa-east-1",
            name="South America (Sao Paulo)",
            vendor=vendor,
            country=countries["BR"],
            city="Sao Paulo",
            founding_year=2011,
            green_energy=False,
        ),
        Datacenter(
            id="us-east-1",
            name="US East (N. Virginia)",
            vendor=vendor,
            country=countries["US"],
            state="Northern Virgina",
            # NOTE city unknown
            founding_year=2006,
            green_energy=True,
        ),
        Datacenter(
            id="us-east-2",
            name="US East (Ohio)",
            vendor=vendor,
            country=countries["US"],
            state="Ohio",
            # NOTE city unknown
            founding_year=2016,
            green_energy=True,
        ),
        Datacenter(
            id="us-west-1",
            name="US West (N. California)",
            vendor=vendor,
            country=countries["US"],
            state="California",
            # NOTE city unknown
            founding_year=2009,
            green_energy=True,
        ),
        Datacenter(
            id="us-west-2",
            name="US West (Oregon)",
            vendor=vendor,
            country=countries["US"],
            state="Oregon",
            # NOTE city unknown
            founding_year=2011,
            green_energy=True,
        ),
    ]

    # look for undocumented (new) regions in AWS
    supported_regions = [d.id for d in datacenters]
    regions = describe_regions()
    for region in regions:
        region_name = region["RegionName"]
        if "gov" in region_name:
            next()
        if region_name not in supported_regions:
            raise NotImplementedError(f"Unsupported AWS datacenter: {region_name}")

    # mark inactive regions
    active_regions = [region["RegionName"] for region in regions]
    for datacenter in datacenters:
        if datacenter.id not in active_regions:
            datacenter.status = "inactive"

    # filter for datacenters enabled for the account
    datacenters = [
        datacenter
        for datacenter in datacenters
        if datacenter.id in [region["RegionName"] for region in regions]
    ]

    # TODO do we really need to return enything? standardize!
    return datacenters


def get_zones(vendor, *args, **kwargs):
    """List all available AWS availability zones."""
    zones = [
        [
            Zone(
                id=zone["ZoneId"],
                name=zone["ZoneName"],
                datacenter=datacenter,
                vendor=vendor,
            )
            for zone in describe_availability_zones(datacenter.id)
        ]
        for datacenter in vendor.datacenters
        if datacenter.status == "active"
    ]
    # TODO check if zone is active
    return ChainMap(*zones)


instance_families = {
    "a": "AWS Graviton",
    "c": "Compute optimized",
    "d": "Dense storage",
    "dl": "Deep Learning",
    "f": "FPGA",
    "g": "Graphics intensive",
    "h": "Cost-effective storage optimized with HDD",
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
    # drop X TB suffix after instance family
    if kind.startswith("u"):
        logger.warning(f"Removing X TB reference from instance family: {kind}")
        kind = re.sub(r"^u-([0-9]*)tb", "u", kind)
    # drop suffixes for now after the dash, e.g. "Mac2-m2", "Mac2-m2pro"
    if "-" in kind:
        logger.warning(f"Truncating instance type after the dash: {kind}")
        kind = kind.split("-")[0]
    family, extras = re.split(r"[0-9]", kind)
    generation = re.findall(r"[0-9]", kind)[0]
    size = instance_type_id.split(".")[1]

    try:
        text = instance_families[family]
    except KeyError as exc:
        raise KeyError(
            "Unknown instance family: " + family + " (e.g. " + instance_type_id + ")"
        ) from exc
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
        return Disk(size=disk["SizeInGB"], storage_type=kind)

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


def server_from_instance_type(instance_type, vendor):
    """Create a SQLModel Server instance from AWS raw API response."""
    it = instance_type["InstanceType"]
    vcpu_info = instance_type["VCpuInfo"]
    cpu_info = instance_type["ProcessorInfo"]
    gpu_info = get_gpu(instance_type)
    storage_info = get_storage(instance_type)
    network_card = instance_type["NetworkInfo"]["NetworkCards"][0]
    # avoid duplicates
    if it not in [s.id for s in vendor.servers]:
        return Server(
            id=it,
            vendor=vendor,
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


def instance_types_of_region(region, vendor):
    """List all available instance types of an AWS region."""
    logger.debug(f"Looking up instance types in region {region}")
    instance_types = describe_instance_types(region)
    return [
        server_from_instance_type(instance_type, vendor)
        for instance_type in instance_types
    ]


def get_instance_types(vendor, *args, **kwargs):
    # TODO drop this in favor of pricing.get_products, as it has info e.g. on instanceFamily
    #      although other fields are messier (e.g. extract memory from string)
    regions = [
        datacenter.id
        for datacenter in vendor.datacenters
        if datacenter.status == "active"
    ]
    # might be instance types specific to a few or even a single region
    instance_types = [instance_types_of_region(region, vendor) for region in regions]
    return list(chain(*instance_types))


def extract_ondemand_price(terms):
    """Extract ondmand price and the currency from AWS Terms object."""
    ondemand_term = list(terms["OnDemand"].values())[0]
    ondemand_pricing = list(ondemand_term["priceDimensions"].values())[0]
    ondemand_pricing = ondemand_pricing["pricePerUnit"]
    if "USD" in ondemand_pricing.keys():
        return (float(ondemand_pricing["USD"]), "USD")
    # get the first currency if USD not found
    return (float(list(ondemand_pricing.values())[0]), list(ondemand_pricing)[0])


def price_from_product(product, vendor):
    attributes = product["product"]["attributes"]
    location = attributes["location"]
    location_type = attributes["locationType"]
    instance_type = attributes["instanceType"]
    try:
        datacenter = [
            d for d in vendor.datacenters if location == d.name or location in d.aliases
        ][0]
    except IndexError:
        logger.debug(f"No AWS region found for location: {location} [{location_type}]")
        return
    except Exception as exc:
        raise exc
    try:
        server = [
            d for d in vendor.servers if d.vendor == vendor and d.id == instance_type
        ][0]
    except IndexError:
        logger.debug(f"No server definition found for {instance_type} @ {location}")
        return
    except Exception as exc:
        raise exc
    price = extract_ondemand_price(product["terms"])
    return ServerPrice(
        vendor=vendor,
        datacenter=datacenter,
        server=server,
        # TODO ingest other OSs
        operating_system="Linux",
        allocation="ondemand",
        price=price[0],
        currency=price[1],
        duration=Duration.HOUR,
    )


def get_prices(vendor, *args, **kwargs):
    products = get_products()
    logger.debug(f"Found {len(products)} products")
    # return [price_from_product(product, vendor) for product in products]
    for product in products:
        # drop Gov regions
        if "GovCloud" not in product["product"]["attributes"]["location"]:
            price_from_product(product, vendor)

    # TODO store raw response
    # TODO reserved pricing options - might decide not to, as not in scope?
    # TODO spot prices
