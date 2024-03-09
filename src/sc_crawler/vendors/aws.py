import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from itertools import chain, repeat
from logging import DEBUG
from typing import List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from cachier import cachier, set_default_params

from ..insert import insert_server_prices
from ..logger import logger
from ..lookup import countries
from ..schemas import (
    Allocation,
    Datacenter,
    Disk,
    Gpu,
    Ipv4Price,
    PriceUnit,
    Server,
    Storage,
    StoragePrice,
    StorageType,
    TrafficDirection,
    TrafficPrice,
    Vendor,
    VendorComplianceLink,
    Zone,
)
from ..str import extract_last_number
from ..utils import jsoned_hash, scmodels_to_dict

# disable caching by default
set_default_params(caching_enabled=False, stale_after=timedelta(days=1))

# ##############################################################################
# Cached boto3 wrappers


@cachier(separate_files=True)
def _boto_describe_instance_types(region):
    ec2 = boto3.client("ec2", region_name=region)
    pages = ec2.get_paginator("describe_instance_types")
    pages = pages.paginate().build_full_result()
    return pages["InstanceTypes"]


@cachier()
def _boto_describe_regions():
    ec2 = boto3.client("ec2")
    return ec2.describe_regions().get("Regions", [])


@cachier()
def _boto_describe_availability_zones(region):
    ec2 = boto3.client("ec2", region_name=region)
    zones = ec2.describe_availability_zones(
        Filters=[
            {"Name": "zone-type", "Values": ["availability-zone"]},
        ],
        AllAvailabilityZones=True,
    )["AvailabilityZones"]
    return zones


@cachier()
def _boto_price_list(region):
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


@cachier(hash_func=jsoned_hash, separate_files=True)
def _boto_get_products(service_code: str, filters: dict):
    """Get products from AWS with auto-paging.

    Args:
        service_code: AWS ServiceCode, e.g. `AmazonEC2`
        filters: `dict` of key/value pairs for `TERM_MATCH` filters
    """
    # pricing API is only available in a few regions
    client = boto3.client("pricing", region_name="us-east-1")

    matched_filters = [
        {"Type": "TERM_MATCH", "Field": k, "Value": v} for k, v in filters.items()
    ]

    paginator = client.get_paginator("get_products")
    # return actual list instead of an iterator to be able to cache on disk
    products = []
    for page in paginator.paginate(ServiceCode=service_code, Filters=matched_filters):
        for product_json in page["PriceList"]:
            product = json.loads(product_json)
            products.append(product)

    logger.debug(f"Found {len(products)} {service_code} products")
    return products


@cachier(separate_files=True)
def _describe_spot_price_history(region):
    ec2 = boto3.client("ec2", region_name=region)
    pager = ec2.get_paginator("describe_spot_price_history")
    pages = pager.paginate(
        # TODO ingests win/mac and others
        Filters=[{"Name": "product-description", "Values": ["Linux/UNIX"]}],
        StartTime=datetime.now(),
    ).build_full_result()
    return pages["SpotPriceHistory"]


# ##############################################################################
# Internal helpers

_instance_families = {
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

_instance_suffixes = {
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


def _annotate_instance_type(instance_type_id):
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
        text = _instance_families[family]
    except KeyError as exc:
        raise KeyError(
            "Unknown instance family: " + family + " (e.g. " + instance_type_id + ")"
        ) from exc
    for k, v in _instance_suffixes.items():
        if k in extras:
            text += " [" + v + "]"
    text += " Gen" + generation
    text += " " + size

    return text


def _get_storage_of_instance_type(instance_type, nvme=False):
    """Get overall storage size and type (tupple) from instance details."""
    if "InstanceStorageInfo" not in instance_type:
        return (0, None)
    info = instance_type["InstanceStorageInfo"]
    storage_size = info["TotalSizeInGB"]
    storage_type = info["Disks"][0].get("Type").lower()
    if storage_type == "ssd" and info.get("NvmeSupport", False):
        storage_type = "nvme ssd"
    return (storage_size, storage_type)


def _array_expand_by_count(array):
    """Expand an array with its items Count field."""
    array = [[a] * a["Count"] for a in array]
    return list(chain(*array))


def _get_storages_of_instance_type(instance_type):
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
    disks = _array_expand_by_count(disks)
    return [to_storage(disk, nvme=info.get("NvmeSupport", False)) for disk in disks]


def _get_gpu_of_instance_type(instance_type):
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


def _get_gpus_of_instance_type(instance_type):
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
    gpus = _array_expand_by_count(gpus)
    return [to_gpu(gpu) for gpu in gpus]


def _make_server_from_instance_type(instance_type, vendor):
    """Create a SQLModel Server instance from AWS raw API response."""
    it = instance_type["InstanceType"]
    vcpu_info = instance_type["VCpuInfo"]
    cpu_info = instance_type["ProcessorInfo"]
    gpu_info = _get_gpu_of_instance_type(instance_type)
    storage_info = _get_storage_of_instance_type(instance_type)
    network_card = instance_type["NetworkInfo"]["NetworkCards"][0]
    Server(
        id=it,
        vendor=vendor,
        name=it,
        description=_annotate_instance_type(it),
        vcpus=vcpu_info["DefaultVCpus"],
        cpu_cores=vcpu_info["DefaultCores"],
        cpu_speed=cpu_info.get("SustainedClockSpeedInGhz", None),
        cpu_architecture=cpu_info["SupportedArchitectures"][0],
        cpu_manufacturer=cpu_info.get("Manufacturer", None),
        memory=instance_type["MemoryInfo"]["SizeInMiB"],
        gpu_count=gpu_info[0],
        gpu_memory=gpu_info[1],
        gpu_name=gpu_info[2],
        gpus=_get_gpus_of_instance_type(instance_type),
        storage_size=storage_info[0],
        storage_type=storage_info[1],
        storages=_get_storages_of_instance_type(instance_type),
        network_speed=network_card["BaselineBandwidthInGbps"],
        billable_unit="hour",
    )


def _list_instance_types_of_region(region, vendor):
    """List all available instance types of an AWS region."""
    logger.debug(f"Looking up instance types in region {region}")
    instance_types = _boto_describe_instance_types(region)
    return [
        _make_server_from_instance_type(instance_type, vendor)
        for instance_type in instance_types
    ]


def _extract_ondemand_price(terms) -> Tuple[float, str]:
    """Extract a single ondemand price and the currency from AWS Terms object.

    Returns:
        Tuple of a price and currency."""
    ondemand_term = list(terms["OnDemand"].values())[0]
    ondemand_pricing = list(ondemand_term["priceDimensions"].values())[0]
    ondemand_pricing = ondemand_pricing["pricePerUnit"]
    if "USD" in ondemand_pricing.keys():
        return (float(ondemand_pricing["USD"]), "USD")
    # get the first currency if USD not found
    return (float(list(ondemand_pricing.values())[0]), list(ondemand_pricing)[0])


def _extract_ondemand_prices(terms) -> Tuple[List[dict], str]:
    """Extract ondemand tiered pricing and the currency from AWS Terms object.

    Returns:
        Tuple of a ordered list of tiered prices and currency."""
    ondemand_terms = list(terms["OnDemand"].values())[0]
    ondemand_terms = list(ondemand_terms["priceDimensions"].values())
    tiers = [
        {
            "lower": float(term.get("beginRange")),
            "upper": float(term.get("endRange")),
            "price": float(list(term.get("pricePerUnit").values())[0]),
        }
        for term in ondemand_terms
    ]
    tiers.sort(key=lambda x: x.get("lower"))
    currency = list(ondemand_terms[0].get("pricePerUnit"))[0]
    return (tiers, currency)


# ##############################################################################
# Public methods to fetch data


def inventory_compliance_frameworks(vendor):
    compliance_frameworks = ["hipaa", "soc2t2"]
    for compliance_framework in compliance_frameworks:
        VendorComplianceLink(
            vendor=vendor,
            compliance_framework_id=compliance_framework,
        )
    vendor.log(f"{len(compliance_frameworks)} compliance frameworks synced.")


def inventory_datacenters(vendor):
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
            id="me-south-1",
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
    regions = _boto_describe_regions()
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
            # note the change of status in the session
            datacenter.vendor.merge_dependent(datacenter)
    vendor.log(f"{len(datacenters)} datacenters synced.")


def inventory_zones(vendor):
    """List all available AWS availability zones."""
    vendor.progress_tracker.start_task(
        name="Scanning datacenters for zones", n=len(vendor.datacenters)
    )
    for datacenter in vendor.datacenters:
        if datacenter.status == "active":
            for zone in _boto_describe_availability_zones(datacenter.id):
                Zone(
                    id=zone["ZoneId"],
                    name=zone["ZoneName"],
                    datacenter=datacenter,
                    vendor=vendor,
                )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    vendor.log(f"{len(vendor.zones)} availability zones synced.")


def inventory_servers(vendor):
    # TODO drop this in favor of pricing.get_products, as it has info e.g. on instanceFamily
    #      although other fields are messier (e.g. extract memory from string)
    vendor.progress_tracker.start_task(
        name="Scanning Datacenters for Servers", n=len(vendor.datacenters)
    )

    def search_servers(datacenter: Datacenter, vendor: Optional[Vendor]) -> List[dict]:
        instance_types = []
        if datacenter.status == "active":
            instance_types = _boto_describe_instance_types(datacenter.id)
            if vendor:
                vendor.log(f"{len(instance_types)} Servers found in {datacenter.id}.")
        if vendor:
            vendor.progress_tracker.advance_task()
        return instance_types

    with ThreadPoolExecutor(max_workers=8) as executor:
        products = executor.map(search_servers, vendor.datacenters, repeat(vendor))
    instance_types = list(chain.from_iterable(products))

    vendor.log(
        f"{len(instance_types)} Servers found in {len(vendor.datacenters)} regions."
    )
    instance_types = list({p["InstanceType"]: p for p in instance_types}.values())
    vendor.log(f"{len(instance_types)} unique Servers found.")
    vendor.progress_tracker.hide_task()

    vendor.progress_tracker.start_task(name="Syncing Servers", n=len(instance_types))
    for instance_type in instance_types:
        _make_server_from_instance_type(instance_type, vendor)
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()


def inventory_server_prices(vendor):
    vendor.progress_tracker.start_task(
        name="Searching for Ondemand Server Prices", n=None
    )
    products = _boto_get_products(
        service_code="AmazonEC2",
        filters={
            # TODO ingest win, mac etc others
            "operatingSystem": "Linux",
            "preInstalledSw": "NA",
            "licenseModel": "No License required",
            "locationType": "AWS Region",
            "capacitystatus": "Used",
            # TODO reserved pricing options - might decide not to, as not in scope?
            "marketoption": "OnDemand",
            # TODO dedicated options?
            "tenancy": "Shared",
        },
    )
    vendor.progress_tracker.hide_task()

    # lookup tables
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name", "aliases"])

    server_prices = []
    vendor.progress_tracker.start_task(
        name="Preprocess Ondemand Prices", n=len(products)
    )
    for product in products:
        try:
            attributes = product["product"]["attributes"]
            # early drop Gov regions
            if "GovCloud" in attributes["location"]:
                continue
            datacenter = datacenters[attributes["location"]]
            price = _extract_ondemand_price(product["terms"])
            for zone in datacenter.zones:
                server_prices.append(
                    {
                        "vendor_id": vendor.id,
                        "datacenter_id": datacenter.id,
                        "zone_id": zone.id,
                        "server_id": attributes["instanceType"],
                        # TODO ingest other OSs
                        "operating_system": "Linux",
                        "allocation": Allocation.ONDEMAND,
                        "price": price[0],
                        "currency": price[1],
                        "unit": PriceUnit.HOUR,
                    }
                )
        except KeyError as e:
            vendor.log(f"Cannot make Ondemand Server Price at {str(e)}", DEBUG)
        finally:
            vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()

    insert_server_prices(server_prices, vendor, price_type="Ondemand")


def inventory_server_prices_spot(vendor):
    vendor.progress_tracker.start_task(
        name="Scanning datacenters for Spot Prices", n=len(vendor.datacenters)
    )

    def get_spot_prices(datacenter: Datacenter, vendor: Vendor) -> List[dict]:
        new = []
        if datacenter.status == "active":
            try:
                new = _describe_spot_price_history(datacenter.id)
                vendor.log(f"{len(new)} Spot Prices found in {datacenter.id}.")
            except ClientError as e:
                vendor.log(f"Cannot get Spot Prices in {datacenter.id}: {str(e)}")
        vendor.progress_tracker.advance_task()
        return new

    with ThreadPoolExecutor(max_workers=8) as executor:
        products = executor.map(get_spot_prices, vendor.datacenters, repeat(vendor))
    products = list(chain.from_iterable(products))
    vendor.log(f"{len(products)} Spot Prices found.")
    vendor.progress_tracker.hide_task()

    # lookup tables
    zones = scmodels_to_dict(vendor.zones, keys=["name"])
    servers = scmodels_to_dict(vendor.servers)

    server_prices = []
    vendor.progress_tracker.start_task(name="Preprocess Spot Prices", n=len(products))
    for product in products:
        try:
            zone = zones[product["AvailabilityZone"]]
            server = servers[product["InstanceType"]]
        except KeyError as e:
            vendor.log("Cannot make Spot Server Price at %s" % str(e), DEBUG)
            continue
        server_prices.append(
            {
                "vendor_id": vendor.id,
                "datacenter_id": zone.datacenter.id,
                "zone_id": zone.id,
                "server_id": server.id,
                # TODO ingest other OSs
                "operating_system": "Linux",
                "allocation": Allocation.SPOT,
                "price": float(product["SpotPrice"]),
                "currency": "USD",
                "unit": PriceUnit.HOUR,
            }
        )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()

    insert_server_prices(server_prices, vendor, price_type="Spot")


storage_types = [
    # previous generation
    "Magnetic",
    # current generation with free IOPS and Throughput tier
    "Cold HDD",
    "Throughput Optimized HDD",
    "General Purpose",
    # current generation with dedicated IOPS (disabled)
    # # "Provisioned IOPS"
]

# https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ebs-volume-types.html
storage_manual_data = {
    "standard": {
        "maxIopsvolume": 200,
        "maxThroughputvolume": 90,
        "minVolumeSize": 1 / 1024,
        "maxVolumeSize": 1,
    },
    "gp2": {
        "maxIopsvolume": 16_000,
        "maxThroughputvolume": 250,
        "minVolumeSize": 1 / 1024,
        "maxVolumeSize": 16,
    },
    "gp3": {
        "maxIopsvolume": 16_000,
        "maxThroughputvolume": 250,
        "minVolumeSize": 1 / 1024,
        "maxVolumeSize": 16,
    },
    "st1": {
        "maxIopsvolume": 500,
        "maxThroughputvolume": 500,
        "minVolumeSize": 125 / 1024,
        "maxVolumeSize": 16,
    },
    "sc1": {
        "maxIopsvolume": 250,
        "maxThroughputvolume": 250,
        "minVolumeSize": 125 / 1024,
        "maxVolumeSize": 16,
    },
}


def search_storage(
    volume_type: str, vendor: Optional[Vendor] = None, location: str = None
) -> List[dict]:
    """Search for storage types with optional progress bar updates and location filter."""
    filters = {"volumeType": volume_type}
    if location:
        filters["location"] = location
    volumes = _boto_get_products(
        service_code="AmazonEC2",
        filters=filters,
    )
    if vendor:
        vendor.progress_tracker.advance_task()
    return volumes


def inventory_storages(vendor):
    vendor.progress_tracker.start_task(
        name="Searching for Storages", n=len(storage_manual_data)
    )

    # look up all volume types in us-east-1
    with ThreadPoolExecutor(max_workers=8) as executor:
        products = executor.map(
            search_storage,
            storage_types,
            repeat(vendor),
            repeat("US East (N. Virginia)"),
        )
    products = list(chain.from_iterable(products))
    vendor.progress_tracker.hide_task()

    for product in products:
        attributes = product["product"]["attributes"]
        product_id = attributes["volumeApiName"]

        def get_attr(key: str) -> float:
            return extract_last_number(
                attributes.get(
                    key,
                    storage_manual_data[product_id][key],
                )
            )

        storage_type = (
            StorageType.HDD if "HDD" in attributes["storageMedia"] else StorageType.SSD
        )
        Storage(
            id=product_id,
            vendor=vendor,
            name=attributes["volumeType"],
            description=attributes["storageMedia"],
            storage_type=storage_type,
            max_iops=get_attr("maxIopsvolume"),
            max_throughput=get_attr("maxThroughputvolume"),
            min_size=get_attr("minVolumeSize") * 1024,
            max_size=get_attr("maxVolumeSize") * 1024,
        )

    vendor.log(f"{len(products)} Storages synced.")


def inventory_storage_prices(vendor):
    vendor_storages = {x.id: x for x in vendor.storages}
    vendor.progress_tracker.start_task(
        name="Searching for Storage Prices", n=len(storage_manual_data)
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        products = executor.map(
            search_storage,
            storage_types,
            repeat(vendor),
        )
    products = list(chain.from_iterable(products))
    vendor.progress_tracker.hide_task()

    # lookup tables
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name", "aliases"])

    vendor.progress_tracker.start_task(name="Syncing Storage Prices", n=len(products))
    for product in products:
        try:
            attributes = product["product"]["attributes"]
            datacenter = datacenters[attributes["location"]]
            price = _extract_ondemand_price(product["terms"])
            StoragePrice(
                vendor=vendor,
                datacenter=datacenter,
                storage=vendor_storages[attributes["volumeApiName"]],
                unit=PriceUnit.GB_MONTH,
                price=price[0],
                currency=price[1],
            )
        except KeyError:
            continue
        finally:
            vendor.progress_tracker.advance_task()

    vendor.progress_tracker.hide_task()
    vendor.log(f"{len(products)} Storage Prices synced.")


def inventory_traffic_prices(vendor):
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name", "aliases"])
    for direction in list(TrafficDirection):
        loc_dir = "toLocation" if direction == TrafficDirection.IN else "fromLocation"
        vendor.progress_tracker.start_task(
            name=f"Searching for {direction.value} Traffic prices", n=None
        )
        products = _boto_get_products(
            service_code="AWSDataTransfer",
            filters={
                "transferType": "AWS " + direction.value.title(),
            },
        )
        vendor.progress_tracker.update_task(
            description=f"Syncing {direction.value} Traffic prices", total=len(products)
        )
        for product in products:
            try:
                datacenter = datacenters[product["product"]["attributes"][loc_dir]]
                price = _extract_ondemand_prices(product["terms"])
                TrafficPrice(
                    vendor=vendor,
                    datacenter=datacenter,
                    price=price[0][-1].get("price"),
                    price_tiered=price,
                    currency=price[1],
                    unit=PriceUnit.GB_MONTH,
                    direction=direction,
                )
            except KeyError:
                continue
            finally:
                vendor.progress_tracker.advance_task()
        vendor.progress_tracker.hide_task()
        vendor.log(f"{len(products)} {direction.value} Traffic prices synced.")


def inventory_ipv4_prices(vendor):
    vendor.progress_tracker.start_task(name="Searching for IPv4 prices", n=None)
    products = _boto_get_products(
        service_code="AmazonVPC",
        filters={
            "group": "VPCPublicIPv4Address",
            "groupDescription": "Hourly charge for In-use Public IPv4 Addresses",
        },
    )
    vendor.progress_tracker.update_task(
        description="Syncing IPv4 prices", total=len(products)
    )
    # lookup tables
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name", "aliases"])
    for product in products:
        try:
            datacenter = datacenters[product["product"]["attributes"]["location"]]
        except KeyError as e:
            vendor.log("Datacenter not found: %s" % str(e), DEBUG)
            continue
        price = _extract_ondemand_price(product["terms"])
        Ipv4Price(
            vendor=vendor,
            datacenter=datacenter,
            price=price[0],
            currency=price[1],
            unit=PriceUnit.HOUR,
        )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    vendor.log(f"{len(products)} IPv4 prices synced.")
