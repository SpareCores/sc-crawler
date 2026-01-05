from concurrent.futures import ThreadPoolExecutor
from functools import cache
from itertools import chain
from logging import WARN
from os import environ
from typing import Optional

from alibabacloud_bssopenapi20171214.client import Client as BssClient
from alibabacloud_bssopenapi20171214.models import QuerySkuPriceListRequest
from alibabacloud_credentials.client import Client as CredClient
from alibabacloud_ecs20140526.client import Client as EcsClient
from alibabacloud_ecs20140526.models import (
    DescribeInstanceTypesRequest,
    DescribeRegionsRequest,
    DescribeZonesRequest,
)
from alibabacloud_tea_openapi.models import Config
from alibabacloud_tea_util.models import RuntimeOptions

from ..inspector import (
    _extract_family,
    _extract_manufacturer,
    _standardize_cpu_model,
    _standardize_gpu_model,
)
from ..logger import logger
from ..lookup import map_compliance_frameworks_to_vendor
from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    PriceUnit,
    StorageType,
    TrafficDirection,
)
from ..tables import Vendor
from ..vendor_helpers import get_region_by_id

# ##############################################################################
# Internal helpers


@cache
def _ecs_client(
    region_id: str = environ.get("ALIBABA_CLOUD_REGION_ID", "eu-central-1"),
) -> EcsClient:
    """Create an Alibaba Cloud client using the default credentials chain.

    Args:
        region_id: The region ID to use, defaults to the `ALIBABA_CLOUD_REGION_ID` env var with a fallback of `eu-central-1`.

    Environment variables required:
    - `ALIBABA_CLOUD_ACCESS_KEY_ID`: The Alibaba Cloud access key ID.
    - `ALIBABA_CLOUD_ACCESS_KEY_SECRET`: The Alibaba Cloud access key secret.
    """
    cred = CredClient()
    config = Config(credential=cred, region_id=region_id)
    return EcsClient(config)


def _ecs_clients(vendor: Vendor) -> dict[str, EcsClient]:
    """Create a dictionary of clients for all regions in the vendor.

    This needs to be called in the main thread before threading,
    as the client sets up signal handlers during client initialization,
    and throws the "signal only works in main thread of the main interpreter"
    `RuntimeError` if called in a thread.

    Args:
        vendor: The vendor to create clients for.

    Returns:
        A dictionary of clients for all regions in the vendor.
    """
    return {
        region.region_id: _ecs_client(region_id=region.region_id)
        for region in vendor.regions
    }


@cache
def _bss_client(
    region_id: str = environ.get("ALIBABA_CLOUD_REGION_ID", "eu-central-1"),
) -> BssClient:
    """Create an Alibaba Cloud BSS client using the default credentials chain."""
    cred = CredClient()
    config = Config(credential=cred, region_id=region_id)
    return BssClient(config)


def _get_sku_prices(
    sku_type: str,
    extra_request_params: Optional[dict] = None,
    vendor: Optional[Vendor] = None,
) -> list[dict]:
    """Fetch SKU prices using the `QuerySkuPriceListRequest` API endpoint.

    Args:
        sku_type: The type of SKU to fetch prices for.
        extra_request_params: Extra parameters to pass to the API request.
        vendor: The Vendor object used for interacting with the progress tracker and logging.

    Returns:
        A list of SKU prices.
    """
    client = _bss_client()
    if extra_request_params is None:
        extra_request_params = {}
    request = QuerySkuPriceListRequest(
        commodity_code="ecs_intl",
        page_size=50,
        lang="en",
        **extra_request_params,
    )
    runtime = RuntimeOptions()
    response = client.query_sku_price_list_with_options(request, runtime)
    skus = [
        sku_price.to_map()
        for sku_price in response.body.data.sku_price_page.sku_price_list
    ]
    pages = response.body.data.sku_price_page.total_count // 50
    if vendor:
        vendor.progress_tracker.start_task(
            name=f"Fetching {sku_type} price pages", total=pages
        )
    while response.body.data.sku_price_page.next_page_token:
        request.next_page_token = response.body.data.sku_price_page.next_page_token
        response = client.query_sku_price_list_with_options(request, runtime)
        skus.extend(
            [
                sku_price.to_map()
                for sku_price in response.body.data.sku_price_page.sku_price_list
            ]
        )
        if vendor:
            vendor.progress_tracker.advance_task()
    if vendor:
        vendor.progress_tracker.hide_task()
    return skus


# ##############################################################################
# Manual data/mapping

locations = {
    # TODO unknown region ids returned by QuerySkuPriceListRequest:
    #  - ap-south-in73-a01 - India (Mumbai) Closed Down
    #  - ap-southeast-au49-a01 - no data found on this at all
    # -------- Mainland China --------
    "cn-qingdao": {
        "alias": ["cn-qingdao-cm5-a01"],
        "city": "Qingdao",
        "lat": 36.0671,
        "lon": 120.3826,
        "country_id": "CN",
        "founding_year": 2012,
    },
    "cn-beijing": {
        "alias": ["cn-beijing-btc-a01"],
        "city": "Beijing",
        "lat": 39.9042,
        "lon": 116.4074,
        "country_id": "CN",
        "founding_year": 2013,
    },
    "cn-zhangjiakou": {
        "alias": ["cn-zhangjiakou-na62-a01"],
        "city": "Zhangjiakou",
        "lat": 40.8244,
        "lon": 114.8875,
        "country_id": "CN",
        "founding_year": 2014,
    },
    "cn-huhehaote": {
        "alias": ["cn-huhehaote-nt12-a01"],
        "city": "Hohhot",
        "lat": 40.8426,
        "lon": 111.7490,
        "country_id": "CN",
        "founding_year": 2017,
    },
    "cn-wulanchabu": {
        "alias": ["cn-wulanchabu-na130-a01"],
        "city": "Ulanqab",
        "lat": 41.0350,
        "lon": 113.1343,
        "country_id": "CN",
        "founding_year": 2020,
    },
    "cn-hangzhou": {
        "alias": ["cn-hangzhou-dg-a01"],
        "city": "Hangzhou",
        "lat": 30.2741,
        "lon": 120.1551,
        "country_id": "CN",
        "founding_year": 2011,
    },
    "cn-shanghai": {
        "alias": ["cn-shanghai-eu13-a01"],
        "city": "Shanghai",
        "lat": 31.2304,
        "lon": 121.4737,
        "country_id": "CN",
        "founding_year": 2015,
    },
    "cn-nanjing": {
        # local region and closing
        "alias": ["cn-nanjing-lnj1-a01"],
        "city": "Nanjing",
        "lat": 32.0603,
        "lon": 118.7969,
        "country_id": "CN",
        "founding_year": 2021,
    },
    "cn-shenzhen": {
        "alias": ["cn-shenzhen-st3-a01"],
        "city": "Shenzhen",
        "lat": 22.5431,
        "lon": 114.0579,
        "country_id": "CN",
        "founding_year": 2014,
    },
    "cn-heyuan": {
        "alias": ["cn-heyuan-sa127-a01"],
        "city": "Heyuan",
        "lat": 23.7405,
        "lon": 114.7003,
        "country_id": "CN",
        "founding_year": 2020,
    },
    "cn-guangzhou": {
        "alias": ["cn-guangzhou-so157-a01"],
        "city": "Guangzhou",
        "lat": 23.1291,
        "lon": 113.2644,
        "country_id": "CN",
        "founding_year": 2020,
    },
    "cn-fuzhou": {
        # local region and closing
        "city": "Fuzhou",
        "lat": 26.0745,
        "lon": 119.2965,
        "country_id": "CN",
        "founding_year": 2022,
    },
    "cn-wuhan-lr": {
        # local region
        "city": "Wuhan",
        "lat": 30.5928,
        "lon": 114.3055,
        "country_id": "CN",
        "founding_year": 2023,
    },
    "cn-chengdu": {
        "alias": ["cn-chengdu-wt97-a01"],
        "city": "Chengdu",
        "lat": 30.5728,
        "lon": 104.0668,
        "country_id": "CN",
        "founding_year": 2020,
    },
    # -------- Hong Kong --------
    "cn-hongkong": {
        "alias": ["cn-hongkong-am4-c04"],
        "city": "Hong Kong",
        "lat": 22.3193,
        "lon": 114.1694,
        "country_id": "HK",
        "founding_year": 2014,
    },
    # -------- Asia Pacific --------
    "ap-northeast-1": {
        "alias": ["ap-northeast-jp59-a01"],
        "city": "Tokyo",
        "lat": 35.6895,
        "lon": 139.6917,
        "country_id": "JP",
        "founding_year": 2016,
    },
    "ap-northeast-2": {
        "city": "Seoul",
        "lat": 37.5665,
        "lon": 126.9780,
        "country_id": "KR",
        "founding_year": 2022,
    },
    "ap-southeast-1": {
        "alias": ["ap-southeast-os30-a01"],
        "city": "Singapore",
        "lat": 1.3521,
        "lon": 103.8198,
        "country_id": "SG",
        "founding_year": 2015,
    },
    "ap-southeast-3": {
        "alias": ["ap-southeast-my88-a01"],
        "city": "Kuala Lumpur",
        "lat": 3.1390,
        "lon": 101.6869,
        "country_id": "MY",
        "founding_year": 2017,
    },
    "ap-southeast-6": {
        "city": "Manila",
        "lat": 14.5995,
        "lon": 120.9842,
        "country_id": "PH",
        "founding_year": 2021,
    },
    "ap-southeast-5": {
        "alias": ["ap-southeast-id35-a01"],
        "city": "Jakarta",
        "lat": 6.2088,
        "lon": 106.8456,
        "country_id": "ID",
        "founding_year": 2018,
    },
    "ap-southeast-7": {
        "city": "Bangkok",
        "lat": 13.7563,
        "lon": 100.5018,
        "country_id": "TH",
        "founding_year": 2022,
    },
    # -------- United States --------
    "us-east-1": {
        "alias": ["us-east-us44-a01"],
        "city": "Virginia",
        "lat": 38.0293,
        "lon": -78.4767,
        "country_id": "US",
        "founding_year": 2015,
    },
    "us-west-1": {
        "alias": ["us-west-ot7-a01"],
        "city": "Silicon Valley",
        "lat": 37.3875,
        "lon": -122.0575,
        "country_id": "US",
        "founding_year": 2014,
    },
    # -------- North America --------
    "na-south-1": {
        "city": "Mexico City",
        "lat": 19.4326,
        "lon": -99.1332,
        "country_id": "MX",
        "founding_year": 2025,
    },
    # -------- Europe --------
    "eu-west-1": {
        "alias": ["eu-west-1-gb33-a01"],
        "city": "London",
        "lat": 51.5074,
        "lon": -0.1278,
        "country_id": "GB",
        "founding_year": 2018,
    },
    "eu-central-1": {
        "alias": ["eu-central-de46-a01"],
        "city": "Frankfurt",
        "lat": 50.1109,
        "lon": 8.6821,
        "country_id": "DE",
        "founding_year": 2016,
    },
    # -------- Middle East --------
    "me-east-1": {
        "alias": ["me-east-db47-a01"],
        "city": "Dubai",
        "lat": 25.2048,
        "lon": 55.2708,
        "country_id": "AE",
        "founding_year": 2016,
    },
    "me-central-1": {
        # partner region
        "city": "Riyadh",
        "lat": 24.7136,
        "lon": 46.6753,
        "country_id": "SA",
        "founding_year": 2022,
    },
}


# ##############################################################################
# Public methods to fetch data


def inventory_compliance_frameworks(vendor):
    """Manual list of compliance frameworks known for Alibaba Cloud.

    Resources: <https://www.alibabacloud.com/en/trust-center/compliance>
    """
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id, ["hipaa", "soc2t2", "iso27001"]
    )


def inventory_regions(vendor):
    """
    List all available Alibaba Cloud regions.

    Data sources:

    - <https://api.alibabacloud.com/document/Ecs/2014-05-26/DescribeRegions>
    - Foundation year collected from <https://www.alibabacloud.com/en/global-locations?_p_lc=1>
    - Aliases (old region names) collected from <https://help.aliyun.com/zh/user-center/product-overview/regional-name-change-announcement>
    """
    request = DescribeRegionsRequest(accept_language="en-US")
    response = _ecs_client().describe_regions(request)
    regions = [region.to_map() for region in response.body.regions.region]

    items = []
    for region in regions:
        location = locations[region.get("RegionId")]
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.get("RegionId"),
                "name": region.get("LocalName"),
                "api_reference": region.get("RegionId"),
                "display_name": f"{location['city']} ({location['country_id']})",
                "aliases": location.get("alias", []),
                "country_id": location.get("country_id"),
                "state": None,  # not available
                "city": location.get("city"),
                "address_line": None,  # not available
                "zip_code": None,  # not available
                "lon": location.get("lon"),
                "lat": location.get("lat"),
                "founding_year": location.get("founding_year"),
                # "Clean electricity accounted for 56.0% of the total electricity consumption at Alibaba Cloud's self-built data centers"
                # https://www.alibabagroup.com/en-US/esg?spm=a3c0i.28208492.4078276800.1.3ee123b78lagGT
                "green_energy": None,
            }
        )
    return items


def inventory_zones(vendor):
    """List all availability zones."""
    vendor.progress_tracker.start_task(
        name="Scanning region(s) for zone(s)", total=len(vendor.regions)
    )
    clients = _ecs_clients(vendor)

    def fetch_zones_for_region(region):
        """Worker function to fetch zones for a single region."""
        request = DescribeZonesRequest(
            region_id=region.region_id, accept_language="en-US"
        )
        try:
            response = clients[region.region_id].describe_zones(request)
            zone_items = []
            for zone in response.body.to_map()["Zones"]["Zone"]:
                zone_items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": region.region_id,
                        "zone_id": zone.get("ZoneId"),
                        "name": zone.get("LocalName"),
                        "api_reference": zone.get("ZoneId"),
                        "display_name": zone.get("LocalName"),
                    }
                )
            return zone_items
        except Exception as e:
            logger.error(f"Failed to get zones for region {region.region_id}: {e}")
            return []
        finally:
            vendor.progress_tracker.advance_task()

    with ThreadPoolExecutor(max_workers=8) as executor:
        items = executor.map(fetch_zones_for_region, vendor.regions)
    items = list(chain.from_iterable(items))
    vendor.progress_tracker.hide_task()
    return items


def inventory_servers(vendor):
    """List all server types at Alibaba Cloud using the `DescribeInstanceTypes` API endpoint."""
    client = _ecs_client()
    request = DescribeInstanceTypesRequest(max_results=1000)
    response = client.describe_instance_types(request)
    instance_types = [
        instance_type.to_map()
        for instance_type in response.body.instance_types.instance_type
    ]
    while response.body.next_token:
        request = DescribeInstanceTypesRequest(
            max_results=1000, next_token=response.body.next_token
        )
        response = client.describe_instance_types(request)
        for instance_type in response.body.instance_types.instance_type:
            instance_types.append(instance_type.to_map())

    CPU_ARCH_MAP = {"X86": CpuArchitecture.X86_64, "ARM": CpuArchitecture.ARM64}
    STORAGE_CATEGORY_MAP = {
        "": None,
        "local_ssd_pro": StorageType.SSD,
        "local_hdd_pro": StorageType.HDD,
    }

    def drop_zero_value(x):
        return None if x == 0 else x

    items = []
    for instance_type in instance_types:
        family = instance_type.get("InstanceTypeFamily")
        vcpus = instance_type.get("CpuCoreCount")
        cpu_model = instance_type.get("PhysicalProcessorModel")
        memory_size_gb = int((instance_type.get("MemorySize") * 1024))
        storage_size = int(
            instance_type.get("LocalStorageAmount", 0)
            * instance_type.get("LocalStorageCapacity", 0)
            # convert GiB to GB
            * 1024**3
            / 1000**3
        )
        storage_type = STORAGE_CATEGORY_MAP[instance_type["LocalStorageCategory"]]
        gpu_count = instance_type.get("GPUAmount", 0)
        gpu_memory_per_gpu = instance_type.get("GPUMemorySize", 0) * 1024  # GiB -> MiB
        gpu_memory_total = gpu_count * gpu_memory_per_gpu
        gpu_model = _standardize_gpu_model(instance_type["GPUSpec"])
        description_parts = [
            f"{vcpus} vCPUs",
            f"{memory_size_gb} GiB RAM",
            f"{storage_size} GB {storage_type.value if storage_type else ''} storage",
            (
                f"{gpu_count}x{gpu_model} {gpu_memory_per_gpu} GiB VRAM"
                if gpu_count and gpu_model
                else None
            ),
        ]
        description = f"{family} family ({', '.join(filter(None, description_parts))})"

        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "server_id": instance_type.get("InstanceTypeId"),
                "name": instance_type.get("InstanceTypeId"),
                "api_reference": instance_type.get("InstanceTypeId"),
                "display_name": instance_type.get("InstanceTypeId"),
                "description": description,
                "family": family,
                "vcpus": vcpus,
                "hypervisor": "KVM",
                "cpu_allocation": CpuAllocation.DEDICATED,
                "cpu_cores": instance_type.get("CpuCoreCount", 0),
                "cpu_speed": drop_zero_value(instance_type.get("CpuSpeedFrequency")),
                "cpu_architecture": CPU_ARCH_MAP[instance_type.get("CpuArchitecture")],
                "cpu_manufacturer": _extract_manufacturer(cpu_model),
                "cpu_family": _extract_family(cpu_model),
                "cpu_model": _standardize_cpu_model(cpu_model),
                "cpu_l1_cache": None,
                "cpu_l2_cache": None,
                "cpu_l3_cache": None,
                "cpu_flags": [],
                "cpus": [],
                "memory_amount": memory_size_gb,
                "memory_generation": None,
                "memory_speed": None,
                "memory_ecc": None,
                "gpu_count": gpu_count,
                "gpu_memory_min": drop_zero_value(int(gpu_memory_per_gpu)),
                "gpu_memory_total": drop_zero_value(int(gpu_memory_total)),
                # TODO fill in from GPUSpec? or just let the inspector fill it in?
                "gpu_manufacturer": None,
                "gpu_family": None,
                "gpu_model": gpu_model,
                "gpus": [],
                "storage_size": storage_size,
                "storage_type": storage_type,
                "storages": [],
                "network_speed": drop_zero_value(
                    instance_type.get("InstanceBandwidthRx", 0) / 1024 / 1000
                ),
                "inbound_traffic": 0,
                "outbound_traffic": 0,
                "ipv4": 0,
            }
        )
    return items


def inventory_server_prices(vendor):
    """Fetch server pricing and regional availability using the `QuerySkuPriceListRequest` API endpoint.

    Alternative approach could be looking at <https://g.alicdn.com/aliyun/ecs-price-info-intl/2.0.375/price/download/instancePrice.json>.
    """
    skus = _get_sku_prices(
        sku_type="server",
        extra_request_params={
            "price_entity_code": "instance_type",
            # filter for Linux prices only for now
            "price_factor_condition_map": {"vm_os_kind": ["linux"]},
        },
        vendor=vendor,
    )

    items = []
    unsupported_regions = set()
    for sku in skus:
        region = get_region_by_id(sku["SkuFactorMap"]["vm_region_no"], vendor)
        if not region:
            unsupported_regions.add(sku["SkuFactorMap"]["vm_region_no"])
            continue
        for zone in region.zones:
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "zone_id": zone.zone_id,
                    "server_id": sku.get("SkuFactorMap").get("instance_type"),
                    "operating_system": sku.get("SkuFactorMap").get("vm_os_kind"),
                    "allocation": Allocation.ONDEMAND,
                    "unit": PriceUnit.HOUR,
                    "price": sku.get("CskuPriceList")[0].get("Price"),
                    "price_upfront": 0,
                    "price_tiered": [],
                    "currency": sku.get("CskuPriceList")[0].get("Currency"),
                }
            )
    for unsupported_region in unsupported_regions:
        vendor.log(f"Found non-supported region: {unsupported_region}", level=WARN)
    return items


def inventory_server_prices_spot(vendor):
    # TODO spot prices can only be queried one-by-one, so let's revisit later?
    # client = _ecs_client()
    # request = DescribePriceRequest(
    #     region_id="eu-central-1",
    #     resource_type="instance",
    #     instance_type="ecs.c6.large",
    #     spot_strategy="SpotAsPriceGo",
    # )
    # response = client.describe_price(request)
    # next(
    #     p.trade_price
    #     for p in response.body.price_info.price.detail_infos.detail_info
    #     if p.resource == "instanceType"
    # )
    return []


def inventory_storages(vendor):
    """List all block storage offerings.

    Data sources:

    - <https://www.alibabacloud.com/help/en/ecs/user-guide/essds>
    - <https://www.alibabacloud.com/help/en/ecs/developer-reference/api-ecs-2014-05-26-createdisk>
    """
    disk_info = [
        # NOTE there's only a single `cloud_essd` ID at Alibaba Cloud,
        # but we suffix with the performance level (PL0, PL1, PL2, PL3)
        # to differentiate them as these are products with very different characteristics
        {
            "name": "cloud_essd-pl0",
            "min_size": 1,
            "max_size": 65536,
            "max_iops": 10000,
            "max_tp": 1440,
            "info": "Enterprise SSD with performance level 0.",
        },
        {
            "name": "cloud_essd-pl1",
            "min_size": 20,
            "max_size": 65536,
            "max_iops": 50000,
            "max_tp": 2800,
            "info": "Enterprise SSD with performance level 1.",
        },
        {
            "name": "cloud_essd-pl2",
            "min_size": 461,
            "max_size": 65536,
            "max_iops": 100000,
            "max_tp": 6000,
            "info": "Enterprise SSD with performance level 2.",
        },
        {
            "name": "cloud_essd-pl3",
            "min_size": 1261,
            "max_size": 65536,
            "max_iops": 1000000,
            "max_tp": 32000,
            "info": "Enterprise SSD with performance level 3.",
        },
        {
            "name": "cloud_ssd",
            "min_size": 20,
            "max_size": 32768,
            "max_iops": 20000,
            "max_tp": 256,
            "info": "Standard SSD.",
        },
        {
            "name": "cloud_efficiency",
            "min_size": 20,
            "max_size": 32768,
            "max_iops": 3000,
            "max_tp": 80,
            "info": "Ultra Disk, older generation.",
        },
        {
            "name": "cloud",
            "min_size": 5,
            "max_size": 2000,
            "max_iops": 300,
            "max_tp": 40,
            "info": "Lowest cost HDD.",
        },
    ]

    items = []
    for disk in disk_info:
        items.append(
            {
                "storage_id": disk.get("name"),
                "vendor_id": vendor.vendor_id,
                "name": disk.get("name"),
                "description": disk.get("info"),
                "storage_type": (
                    StorageType.HDD if disk.get("name") == "cloud" else StorageType.SSD
                ),
                "max_iops": disk.get("max_iops"),
                "max_throughput": disk.get("max_tp"),
                "min_size": disk.get("min_size"),
                "max_size": disk.get("max_size"),
            }
        )
    return items


def inventory_storage_prices(vendor):
    """Fetch server prices using the `QuerySkuPriceListRequest` API endpoint."""
    skus = _get_sku_prices(
        sku_type="storage",
        extra_request_params={"price_entity_code": "datadisk"},
        vendor=vendor,
    )

    items = []
    unsupported_regions = set()
    for sku in skus:
        storage_id = sku["SkuFactorMap"]["datadisk_category"]
        pl = sku["SkuFactorMap"]["datadisk_performance_level"]
        if storage_id in ["cloud", "cloud_ssd", "cloud_efficiency"]:
            # no diff in performance levels, pick one
            if pl != "PL1":
                continue
        else:
            # keep the 4 performance levels
            if pl not in ["PL0", "PL1", "PL2", "PL3"]:
                continue
            storage_id = storage_id + "-" + pl.lower()
        region_id = sku["SkuFactorMap"]["vm_region_no"]
        region = get_region_by_id(region_id, vendor)
        if not region:
            unsupported_regions.add(region_id)
            continue
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "storage_id": storage_id,
                "unit": PriceUnit.GB_MONTH,
                "price": sku["CskuPriceList"][0]["Price"],
                "currency": sku["CskuPriceList"][0]["Currency"],
            }
        )
    for unsupported_region in unsupported_regions:
        vendor.log(f"Found non-supported region: {unsupported_region}", level=WARN)
    return items


def inventory_traffic_prices(vendor):
    """Collect inbound and outbound traffic prices of Alibaba Cloud regions.

    Inbound is free as per <https://www.alibabacloud.com/help/en/ecs/public-bandwidth>.
    Outbound traffic pricing collected from the `QuerySkuPriceListRequest` API endpoint.

    Account level tiering information can be found at <https://www.alibabacloud.com/help/en/cdt/internet-data-transfers/#4a98c9ee8eemn>.
    """
    items = []
    skus = _get_sku_prices(
        sku_type="traffic",
        extra_request_params={"price_entity_code": "vm_flow_out"},
        # vendor=vendor,
    )
    unsupported_regions = set()
    for sku in skus:
        region_id = sku["SkuFactorMap"]["vm_region_no"]
        region = get_region_by_id(region_id, vendor)
        if not region:
            unsupported_regions.add(region_id)
            continue
        price = next(p for p in sku["CskuPriceList"] if float(p["Price"]) > 0)
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "price": price["Price"],
                "price_tiered": [],
                "currency": price["Currency"],
                "unit": PriceUnit.GB_MONTH,
                "direction": TrafficDirection.OUT,
            }
        )
        # incoming traffic is free
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "price": 0,
                "price_tiered": [],
                "currency": price["Currency"],
                "unit": PriceUnit.GB_MONTH,
                "direction": TrafficDirection.IN,
            }
        )
    for unsupported_region in unsupported_regions:
        vendor.log(f"Found non-supported region: {unsupported_region}", level=WARN)
    return items


def inventory_ipv4_prices(vendor):
    """Static IPv4 pricing of Alibaba Cloud regions.

    Static (not Elastic) IP addresses are free, you only pay for bandwidth or traffic
    as per <https://www.alibabacloud.com/help/en/ecs/user-guide/public-ip-address?spm=a2c63.p38356.0.i1#52c0fa8bbcee6>.
    """
    items = []
    for region in vendor.regions:
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "price": 0,
                "currency": "USD",
                "unit": PriceUnit.MONTH,
            }
        )
    return items
