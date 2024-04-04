import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from itertools import chain, repeat
from logging import DEBUG
from statistics import mode
from typing import List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError
from cachier import cachier, set_default_params

from ..logger import logger
from ..str_utils import extract_last_number
from ..table_fields import (
    Allocation,
    CpuAllocation,
    Disk,
    Gpu,
    PriceTier,
    PriceUnit,
    StorageType,
    TrafficDirection,
)
from ..tables import (
    Datacenter,
    Vendor,
)
from ..utils import float_inf_to_str, jsoned_hash, scmodels_to_dict

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
    # https://aws.amazon.com/ec2/instance-types/g6/
    "gr": "Graphics intensive with a one to eight ratio of vCPU to memory",
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
    """Get overall GPU count, min and total memory, and manufacturer, name."""
    if "GpuInfo" not in instance_type:
        return (0, None, None, None, None)
    info = instance_type["GpuInfo"]
    memory_min = min([gpu["MemoryInfo"]["SizeInMiB"] for gpu in info["Gpus"]])
    memory_total = info["TotalGpuMemoryInMiB"]
    count = sum([gpu["Count"] for gpu in info["Gpus"]])
    # most common
    manufacturer = mode([gpu["Manufacturer"] for gpu in info["Gpus"]])
    model = mode([gpu["Name"] for gpu in info["Gpus"]])
    return (count, memory_min, memory_total, manufacturer, model)


def _get_gpus_of_instance_type(instance_type):
    """Get individual GPUs as an array."""
    if "GpuInfo" not in instance_type:
        return []
    info = instance_type["GpuInfo"]

    def to_gpu(gpu):
        return Gpu(
            manufacturer=gpu["Manufacturer"],
            model=gpu["Name"],
            memory=gpu["MemoryInfo"]["SizeInMiB"],
        )

    # replicate number of disks
    gpus = info["Gpus"]
    gpus = _array_expand_by_count(gpus)
    return [to_gpu(gpu) for gpu in gpus]


def _make_server_from_instance_type(instance_type, vendor) -> dict:
    """Create a SQLModel Server-compatible dict from AWS raw API response."""
    it = instance_type["InstanceType"]
    allocation = CpuAllocation.DEDICATED
    if instance_type.get("BurstablePerformanceSupported", False):
        allocation = CpuAllocation.BURSTABLE
    vcpu_info = instance_type["VCpuInfo"]
    cpu_info = instance_type["ProcessorInfo"]
    gpu_info = _get_gpu_of_instance_type(instance_type)
    storage_info = _get_storage_of_instance_type(instance_type)
    network_card = instance_type["NetworkInfo"]["NetworkCards"][0]
    return {
        "server_id": it,
        "vendor_id": vendor.vendor_id,
        "name": it,
        "description": _annotate_instance_type(it),
        "hypervisor": instance_type.get("Hypervisor", None),
        "vcpus": vcpu_info["DefaultVCpus"],
        "cpu_allocation": allocation,
        "cpu_cores": vcpu_info["DefaultCores"],
        "cpu_speed": cpu_info.get("SustainedClockSpeedInGhz", None),
        "cpu_architecture": cpu_info["SupportedArchitectures"][0],
        "cpu_manufacturer": cpu_info.get("Manufacturer", None),
        "memory": instance_type["MemoryInfo"]["SizeInMiB"],
        "gpu_count": gpu_info[0],
        "gpu_memory_min": gpu_info[1],
        "gpu_memory_total": gpu_info[2],
        "gpu_manufacturer": gpu_info[3],
        "gpu_model": gpu_info[4],
        "gpus": _get_gpus_of_instance_type(instance_type),
        "storage_size": storage_info[0],
        "storage_type": storage_info[1],
        "storages": _get_storages_of_instance_type(instance_type),
        "network_speed": network_card["BaselineBandwidthInGbps"],
    }


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
            "upper": float_inf_to_str(float(term.get("endRange"))),
            "price": float(list(term.get("pricePerUnit").values())[0]),
        }
        for term in ondemand_terms
    ]
    tiers.sort(key=lambda x: x.get("lower"))
    currency = list(ondemand_terms[0].get("pricePerUnit"))[0]
    return (tiers, currency)


def _search_storage(
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


# ##############################################################################
# Public methods to fetch data


def inventory_compliance_frameworks(vendor):
    """Manual list of compliance frameworks known for AWS."""
    compliance_frameworks = ["hipaa", "soc2t2"]
    items = []
    for compliance_framework in compliance_frameworks:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "compliance_framework_id": compliance_framework,
            }
        )
    return items


def inventory_datacenters(vendor):
    """List all available AWS datacenters via `boto3` calls.

    Some data sources are not available from APIs, and were collected manually:

    - launch date: <https://aws.amazon.com/about-aws/global-infrastructure/regions_az/>
    - energy source: <https://sustainability.aboutamazon.com/products-services/the-cloud?energyType=true#renewable-energy>
    """  # noqa: E501
    datacenters = [
        {
            "datacenter_id": "af-south-1",
            "name": "Africa (Cape Town)",
            "vendor_id": vendor.vendor_id,
            "country_id": "ZA",
            "city": "Cape Town",
            "founding_year": 2020,
            "green_energy": False,
        },
        {
            "datacenter_id": "ap-east-1",
            "name": "Asia Pacific (Hong Kong)",
            "vendor_id": vendor.vendor_id,
            "country_id": "HK",
            "city": "Hong Kong",
            "founding_year": 2019,
            "green_energy": False,
        },
        {
            "datacenter_id": "ap-northeast-1",
            "name": "Asia Pacific (Tokyo)",
            "vendor_id": vendor.vendor_id,
            "country_id": "JP",
            "city": "Tokyo",
            "founding_year": 2011,
            "green_energy": False,
        },
        {
            "datacenter_id": "ap-northeast-2",
            "name": "Asia Pacific (Seoul)",
            "vendor_id": vendor.vendor_id,
            "country_id": "KR",
            "city": "Seoul",
            "founding_year": 2016,
            "green_energy": False,
        },
        {
            "datacenter_id": "ap-northeast-3",
            "name": "Asia Pacific (Osaka)",
            "vendor_id": vendor.vendor_id,
            "country_id": "JP",
            "city": "Osaka",
            "founding_year": 2021,
            "green_energy": False,
        },
        {
            "datacenter_id": "ap-south-1",
            "name": "Asia Pacific (Mumbai)",
            "vendor_id": vendor.vendor_id,
            "country_id": "IN",
            "city": "Mumbai",
            "founding_year": 2016,
            "green_energy": True,
        },
        {
            "datacenter_id": "ap-south-2",
            "name": "Asia Pacific (Hyderabad)",
            "vendor_id": vendor.vendor_id,
            "country_id": "IN",
            "city": "Hyderabad",
            "founding_year": 2022,
            "green_energy": True,
        },
        {
            "datacenter_id": "ap-southeast-1",
            "name": "Asia Pacific (Singapore)",
            "vendor_id": vendor.vendor_id,
            "country_id": "SG",
            "city": "Singapore",
            "founding_year": 2010,
            "green_energy": False,
        },
        {
            "datacenter_id": "ap-southeast-2",
            "name": "Asia Pacific (Sydney)",
            "vendor_id": vendor.vendor_id,
            "country_id": "AU",
            "city": "Sydney",
            "founding_year": 2012,
            "green_energy": False,
        },
        {
            "datacenter_id": "ap-southeast-3",
            "name": "Asia Pacific (Jakarta)",
            "vendor_id": vendor.vendor_id,
            "country_id": "ID",
            "city": "Jakarta",
            "founding_year": 2021,
            "green_energy": False,
        },
        {
            "datacenter_id": "ap-southeast-4",
            "name": "Asia Pacific (Melbourne)",
            "vendor_id": vendor.vendor_id,
            "country_id": "AU",
            "city": "Melbourne",
            "founding_year": 2023,
            "green_energy": False,
        },
        {
            "datacenter_id": "ca-central-1",
            "name": "Canada (Central)",
            "vendor_id": vendor.vendor_id,
            "country_id": "CA",
            "city": "Quebec",  # NOTE needs city name
            "founding_year": 2016,
            "green_energy": True,
        },
        {
            "datacenter_id": "ca-west-1",
            "name": "Canada West (Calgary)",
            "vendor_id": vendor.vendor_id,
            "country_id": "CA",
            "city": "Calgary",
            "founding_year": 2023,
            "green_energy": False,
        },
        {
            "datacenter_id": "cn-north-1",
            "name": "China (Beijing)",
            "vendor_id": vendor.vendor_id,
            "country_id": "CN",
            "city": "Beijing",
            "founding_year": 2016,
            "green_energy": True,
        },
        {
            "datacenter_id": "cn-northwest-1",
            "name": "China (Ningxia)",
            "vendor_id": vendor.vendor_id,
            "country_id": "CN",
            "city": "Ningxia",  # NOTE needs city name
            "founding_year": 2017,
            "green_energy": True,
        },
        {
            "datacenter_id": "eu-central-1",
            "name": "Europe (Frankfurt)",
            "aliases": ["EU (Frankfurt)"],
            "vendor_id": vendor.vendor_id,
            "country_id": "DE",
            "city": "Frankfurt",
            "founding_year": 2014,
            "green_energy": True,
        },
        {
            "datacenter_id": "eu-central-2",
            "name": "Europe (Zurich)",
            "vendor_id": vendor.vendor_id,
            "country_id": "CH",
            "city": "Zurich",
            "founding_year": 2022,
            "green_energy": True,
        },
        {
            "datacenter_id": "eu-north-1",
            "name": "Europe (Stockholm)",
            "aliases": ["EU (Stockholm)"],
            "vendor_id": vendor.vendor_id,
            "country_id": "SE",
            "city": "Stockholm",
            "founding_year": 2018,
            "green_energy": True,
        },
        {
            "datacenter_id": "eu-south-1",
            "name": "Europe (Milan)",
            "aliases": ["EU (Milan)"],
            "vendor_id": vendor.vendor_id,
            "country_id": "IT",
            "city": "Milan",
            "founding_year": 2020,
            "green_energy": True,
        },
        {
            "datacenter_id": "eu-south-2",
            "name": "Europe (Spain)",
            "vendor_id": vendor.vendor_id,
            "country_id": "ES",
            "city": "Aragón",  # NOTE needs city name
            "founding_year": 2022,
            "green_energy": True,
        },
        {
            "datacenter_id": "eu-west-1",
            "name": "Europe (Ireland)",
            "aliases": ["EU (Ireland)"],
            "vendor_id": vendor.vendor_id,
            "country_id": "IE",
            "city": "Dublin",
            "founding_year": 2007,
            "green_energy": True,
        },
        {
            "datacenter_id": "eu-west-2",
            "name": "Europe (London)",
            "aliases": ["EU (London)"],
            "vendor_id": vendor.vendor_id,
            "country_id": "GB",
            "city": "London",
            "founding_year": 2016,
            "green_energy": True,
        },
        {
            "datacenter_id": "eu-west-3",
            "name": "Europe (Paris)",
            "aliases": ["EU (Paris)"],
            "vendor_id": vendor.vendor_id,
            "country_id": "FR",
            "city": "Paris",
            "founding_year": 2017,
            "green_energy": True,
        },
        {
            "datacenter_id": "il-central-1",
            "name": "Israel (Tel Aviv)",
            "vendor_id": vendor.vendor_id,
            "country_id": "IL",
            "city": "Tel Aviv",
            "founding_year": 2023,
            "green_energy": False,
        },
        {
            "datacenter_id": "me-central-1",
            "name": "Middle East (UAE)",
            "vendor_id": vendor.vendor_id,
            "country_id": "AE",
            # NOTE city unknown
            "founding_year": 2022,
            "green_energy": False,
        },
        {
            "datacenter_id": "me-south-1",
            "name": "Middle East (Bahrain)",
            "vendor_id": vendor.vendor_id,
            "country_id": "BH",
            # NOTE city unknown
            "founding_year": 2019,
            "green_energy": False,
        },
        {
            "datacenter_id": "sa-east-1",
            "name": "South America (Sao Paulo)",
            "vendor_id": vendor.vendor_id,
            "country_id": "BR",
            "city": "Sao Paulo",
            "founding_year": 2011,
            "green_energy": False,
        },
        {
            "datacenter_id": "us-east-1",
            "name": "US East (N. Virginia)",
            "vendor_id": vendor.vendor_id,
            "country_id": "US",
            "state": "Northern Virgina",
            # NOTE city unknown
            "founding_year": 2006,
            "green_energy": True,
        },
        {
            "datacenter_id": "us-east-2",
            "name": "US East (Ohio)",
            "vendor_id": vendor.vendor_id,
            "country_id": "US",
            "state": "Ohio",
            # NOTE city unknown
            "founding_year": 2016,
            "green_energy": True,
        },
        {
            "datacenter_id": "us-west-1",
            "name": "US West (N. California)",
            "vendor_id": vendor.vendor_id,
            "country_id": "US",
            "state": "California",
            # NOTE city unknown
            "founding_year": 2009,
            "green_energy": True,
        },
        {
            "datacenter_id": "us-west-2",
            "name": "US West (Oregon)",
            "vendor_id": vendor.vendor_id,
            "country_id": "US",
            "state": "Oregon",
            # NOTE city unknown
            "founding_year": 2011,
            "green_energy": True,
        },
    ]

    # look for undocumented (new) regions in AWS
    supported_regions = [d["datacenter_id"] for d in datacenters]
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
        if datacenter["datacenter_id"] in active_regions:
            datacenter["status"] = "active"
        else:
            datacenter["status"] = "inactive"

    return datacenters


def inventory_zones(vendor):
    """List all available AWS availability zones via `boto3` calls."""
    vendor.progress_tracker.start_task(
        name="Scanning datacenter(s) for zone(s)", total=len(vendor.datacenters)
    )

    def get_zones(datacenter: Datacenter, vendor: Vendor) -> List[dict]:
        new = []
        if datacenter.status == "active":
            for zone in _boto_describe_availability_zones(datacenter.datacenter_id):
                new.append(
                    {
                        "zone_id": zone["ZoneId"],
                        "name": zone["ZoneName"],
                        "datacenter_id": datacenter.datacenter_id,
                        "vendor_id": vendor.vendor_id,
                    }
                )
        vendor.progress_tracker.advance_task()
        return new

    with ThreadPoolExecutor(max_workers=8) as executor:
        zones = executor.map(get_zones, vendor.datacenters, repeat(vendor))
    zones = list(chain.from_iterable(zones))
    vendor.progress_tracker.hide_task()
    return zones


def inventory_servers(vendor):
    """List all available AWS instance types in all regions via `boto3` calls."""
    # TODO drop this in favor of pricing.get_products, as it has info e.g. on instanceFamily
    #      although other fields are messier (e.g. extract memory from string)
    vendor.progress_tracker.start_task(
        name="Scanning datacenter(s) for server(s)", total=len(vendor.datacenters)
    )

    def search_servers(datacenter: Datacenter, vendor: Optional[Vendor]) -> List[dict]:
        instance_types = []
        if datacenter.status == "active":
            instance_types = _boto_describe_instance_types(datacenter.datacenter_id)
            if vendor:
                vendor.log(
                    f"{len(instance_types)} server(s) found in {datacenter.datacenter_id}."
                )
        if vendor:
            vendor.progress_tracker.advance_task()
        return instance_types

    with ThreadPoolExecutor(max_workers=8) as executor:
        products = executor.map(search_servers, vendor.datacenters, repeat(vendor))
    instance_types = list(chain.from_iterable(products))

    vendor.log(
        f"{len(instance_types)} server(s) found in {len(vendor.datacenters)} regions."
    )
    instance_types = list({p["InstanceType"]: p for p in instance_types}.values())
    vendor.log(f"{len(instance_types)} unique server(s) found.")
    vendor.progress_tracker.hide_task()

    vendor.progress_tracker.start_task(
        name="Preprocessing server(s)", total=len(instance_types)
    )
    servers = []
    for instance_type in instance_types:
        servers.append(_make_server_from_instance_type(instance_type, vendor))
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return servers


def inventory_server_prices(vendor):
    """List all on-demand instance prices in all regions via `boto3` calls."""
    vendor.progress_tracker.start_task(
        name="Searching for ondemand server_price(s)", total=None
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
    servers = scmodels_to_dict(vendor.servers, keys=["server_id"])

    server_prices = []
    vendor.progress_tracker.start_task(
        name="Preprocess ondemand server_price(s)", total=len(products)
    )
    for product in products:
        try:
            attributes = product["product"]["attributes"]
            # early drop Gov regions
            if "GovCloud" in attributes["location"]:
                continue
            datacenter = datacenters[attributes["location"]]
            server = servers[attributes["instanceType"]]
            price = _extract_ondemand_price(product["terms"])
            for zone in datacenter.zones:
                server_prices.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "datacenter_id": datacenter.datacenter_id,
                        "zone_id": zone.zone_id,
                        "server_id": server.server_id,
                        # TODO ingest other OSs
                        "operating_system": "Linux",
                        "allocation": Allocation.ONDEMAND,
                        "price": price[0],
                        "currency": price[1],
                        "unit": PriceUnit.HOUR,
                    }
                )
        except KeyError as e:
            vendor.log(
                f"Cannot make ondemand server_price due to unknown {str(e)}: {str(attributes)}",
                DEBUG,
            )
        finally:
            vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return server_prices


def inventory_server_prices_spot(vendor):
    """List all spot instance prices in all availability zones via `boto3` calls."""
    vendor.progress_tracker.start_task(
        name="Scanning datacenters for spot server_price(s)",
        total=len(vendor.datacenters),
    )

    def get_spot_prices(datacenter: Datacenter, vendor: Vendor) -> List[dict]:
        new = []
        if datacenter.status == "active":
            try:
                new = _describe_spot_price_history(datacenter.datacenter_id)
                vendor.log(
                    f"{len(new)} spot server_price(s) found in {datacenter.datacenter_id}."
                )
            except ClientError as e:
                vendor.log(
                    f"Cannot get spot server_price in {datacenter.datacenter_id}: {str(e)}"
                )
        vendor.progress_tracker.advance_task()
        return new

    with ThreadPoolExecutor(max_workers=8) as executor:
        products = executor.map(get_spot_prices, vendor.datacenters, repeat(vendor))
    products = list(chain.from_iterable(products))
    vendor.log(f"{len(products)} spot server_price(s) found.")
    vendor.progress_tracker.hide_task()

    # lookup tables
    zones = scmodels_to_dict(vendor.zones, keys=["name"])
    servers = scmodels_to_dict(vendor.servers, keys=["server_id"])

    server_prices = []
    vendor.progress_tracker.start_task(
        name="Preprocess spot server_price(s)", total=len(products)
    )
    for product in products:
        try:
            zone = zones[product["AvailabilityZone"]]
            server = servers[product["InstanceType"]]
        except KeyError as e:
            vendor.log(
                f"Cannot make ondemand server_price due to unknown {str(e)}: {str(product)}",
                DEBUG,
            )
            continue
        server_prices.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": zone.datacenter.datacenter_id,
                "zone_id": zone.zone_id,
                "server_id": server.server_id,
                # TODO ingest other OSs
                "operating_system": "Linux",
                "allocation": Allocation.SPOT,
                "price": float(product["SpotPrice"]),
                "currency": "USD",
                "unit": PriceUnit.HOUR,
                # use reported time instead of current timestamp
                "observed_at": product["Timestamp"],
            }
        )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return server_prices


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


def inventory_storages(vendor):
    """List all storage types via `boto3` calls."""
    vendor.progress_tracker.start_task(
        name="Searching for storages", total=len(storage_manual_data)
    )

    # look up all volume types in us-east-1
    with ThreadPoolExecutor(max_workers=8) as executor:
        products = executor.map(
            _search_storage,
            storage_types,
            repeat(vendor),
            repeat("US East (N. Virginia)"),
        )
    products = list(chain.from_iterable(products))
    vendor.progress_tracker.hide_task()

    storages = []
    for product in products:
        attributes = product["product"]["attributes"]
        product_id = attributes["volumeApiName"]

        def get_attr(key: str) -> float:
            return extract_last_number(
                str(
                    attributes.get(
                        key,
                        storage_manual_data[product_id][key],
                    )
                )
            )

        storage_type = (
            StorageType.HDD if "HDD" in attributes["storageMedia"] else StorageType.SSD
        )
        storages.append(
            {
                "storage_id": product_id,
                "vendor_id": vendor.vendor_id,
                "name": attributes["volumeType"],
                "description": attributes["storageMedia"],
                "storage_type": storage_type,
                "max_iops": get_attr("maxIopsvolume"),
                "max_throughput": get_attr("maxThroughputvolume"),
                "min_size": get_attr("minVolumeSize") * 1024,
                "max_size": get_attr("maxVolumeSize") * 1024,
            }
        )

    return storages


def inventory_storage_prices(vendor):
    """List all storage prices in all regions via `boto3` calls."""
    vendor.progress_tracker.start_task(
        name="Searching for storage_price(s)", total=len(storage_manual_data)
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        products = executor.map(
            _search_storage,
            storage_types,
            repeat(vendor),
        )
    products = list(chain.from_iterable(products))
    vendor.progress_tracker.hide_task()
    vendor.log(f"Found {len(products)} storage_price(s).")

    # lookup tables
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name", "aliases"])

    vendor.progress_tracker.start_task(
        name="Preprocessing storage_price(s)", total=len(products)
    )
    prices = []
    for product in products:
        try:
            attributes = product["product"]["attributes"]
            datacenter = datacenters[attributes["location"]]
            price = _extract_ondemand_price(product["terms"])
            prices.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "datacenter_id": datacenter.datacenter_id,
                    "storage_id": attributes["volumeApiName"],
                    "unit": PriceUnit.GB_MONTH,
                    "price": price[0],
                    "currency": price[1],
                }
            )
        except KeyError:
            continue
        finally:
            vendor.progress_tracker.advance_task()

    vendor.progress_tracker.hide_task()
    return prices


def inventory_traffic_prices(vendor):
    """List all inbound and outbound traffic prices in all regions via `boto3` calls."""
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name", "aliases"])
    for direction in list(TrafficDirection):
        loc_dir = "toLocation" if direction == TrafficDirection.IN else "fromLocation"
        vendor.progress_tracker.start_task(
            name=f"Searching for {direction.value} traffic_price(s)", total=None
        )
        products = _boto_get_products(
            service_code="AWSDataTransfer",
            filters={
                "transferType": "AWS " + direction.value.title(),
            },
        )
        vendor.log(f"Found {len(products)} {direction.value} traffic_price(s).")
        vendor.progress_tracker.update_task(
            description=f"Syncing {direction.value} traffic_price(s)",
            total=len(products),
        )
        items = []
        for product in products:
            try:
                datacenter = datacenters[product["product"]["attributes"][loc_dir]]
                prices = _extract_ondemand_prices(product["terms"])
                price = [PriceTier.model_validate(p).model_dump() for p in prices[0]]
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "datacenter_id": datacenter.datacenter_id,
                        "price": max([t["price"] for t in prices[0]]),
                        "price_tiered": price,
                        "currency": prices[1],
                        "unit": PriceUnit.GB_MONTH,
                        "direction": direction,
                    }
                )
            except KeyError:
                continue
            finally:
                vendor.progress_tracker.advance_task()
        vendor.progress_tracker.hide_task()
        return items


def inventory_ipv4_prices(vendor):
    """List IPV4 prices in all regions via `boto3` calls."""
    vendor.progress_tracker.start_task(name="Searching for ipv4_price(s)", total=None)
    products = _boto_get_products(
        service_code="AmazonVPC",
        filters={
            "group": "VPCPublicIPv4Address",
            "groupDescription": "Hourly charge for In-use Public IPv4 Addresses",
        },
    )
    vendor.log(f"Found {len(products)} ipv4_price(s).")
    vendor.progress_tracker.update_task(
        description="Syncing ipv4_price(s)", total=len(products)
    )
    # lookup tables
    datacenters = scmodels_to_dict(vendor.datacenters, keys=["name", "aliases"])
    items = []
    for product in products:
        try:
            datacenter = datacenters[product["product"]["attributes"]["location"]]
        except KeyError as e:
            vendor.log("datacenter not found: %s" % str(e), DEBUG)
            continue
        price = _extract_ondemand_price(product["terms"])
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "datacenter_id": datacenter.datacenter_id,
                "price": price[0],
                "currency": price[1],
                "unit": PriceUnit.HOUR,
            }
        )
        vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return items
