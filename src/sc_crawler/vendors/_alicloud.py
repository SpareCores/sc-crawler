"""Inventory of Alibaba Cloud via its APIs: servers, storages, traffic, IPv4 addresses and managed databases, with their prices."""

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import cache
from itertools import chain
from logging import CRITICAL, DEBUG, INFO, WARN, getLogger
from os import environ
from random import shuffle
from re import search, sub
from time import monotonic, sleep, time
from typing import Collection, Optional

from alibabacloud_bssopenapi20171214.client import Client as BssClient
from alibabacloud_bssopenapi20171214.models import QuerySkuPriceListRequest
from alibabacloud_credentials.client import Client as CredClient
from alibabacloud_ecs20140526.client import Client as EcsClient
from alibabacloud_ecs20140526.models import (
    DescribeAvailableResourceRequest,
    DescribeInstanceTypesRequest,
    DescribePriceRequest,
    DescribePriceRequestDataDisk,
    DescribePriceRequestSystemDisk,
    DescribePriceResponseBody,
    DescribeRegionsRequest,
    DescribeSpotAdviceRequest,
    DescribeZonesRequest,
)
from alibabacloud_rds20140815.client import Client as RdsClient
from alibabacloud_rds20140815.models import (
    DescribeAvailableClassesRequest,
    DescribeAvailableZonesRequest,
    DescribePriceRequestDBNode,
    ListClassesRequest,
)
from alibabacloud_rds20140815.models import (
    DescribePriceRequest as RdsDescribePriceRequest,
)
from alibabacloud_tea_openapi.models import Config
from alibabacloud_tea_util.models import RuntimeOptions
from cachier import cachier

from ..inspector import (
    _extract_family,
    _extract_manufacturer,
    _standardize_cpu_model,
    _standardize_gpu_count,
    _standardize_gpu_model,
)
from ..logger import logger
from ..lookup import map_compliance_frameworks_to_vendor
from ..sentry import sentry_capture_or_raise
from ..table_fields import (
    AcceleratorType,
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    DatabaseEngine,
    DatabaseHaLevel,
    DatabaseHaStrategy,
    DatabaseSecurityFeature,
    DatabaseStorageScope,
    DatabaseWireProtocol,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)
from ..tables import ServerPrice, Vendor
from ..utils import _GIB_TO_GB, _HOURS_PER_MONTH, jsoned_hash
from ..vendor_helpers import (
    get_region_by_id,
    server_status_from_availability_categories,
)

# StatusCategory values:
# *   WithStock: The resources are available and can be continuously
#     replenished.
# *   ClosedWithStock: Inventory is available, but resources will not be
#     replenished. The ability to guarantee the supply of inventory is low.
#     We recommend selecting a product specification in the WithStock state.
# *   WithoutStock: The resource is out of stock and will be replenished.
#     We recommend using other resources that are in stock.
# *   ClosedWithoutStock: The resource is out of stock and will no longer
#     be replenished. We recommend using other resources that are in stock.
_ALICLOUD_STATUS_CATEGORY_TO_SERVER_STATUS = {
    "WithStock": Status.ACTIVE,
    "ClosedWithStock": Status.PLANNED_FOR_RETIREMENT,
    "WithoutStock": Status.INACTIVE,
    "ClosedWithoutStock": Status.RETIRED,
}
# Server status over all zones: out of stock instance types are still offered
# (stock is replenished), only their per-zone prices are INACTIVE.
_ALICLOUD_STATUS_CATEGORY_TO_SERVER_LIFECYCLE = {
    **_ALICLOUD_STATUS_CATEGORY_TO_SERVER_STATUS,
    "WithoutStock": Status.ACTIVE,
}

# ##############################################################################
# Internal helpers


def _alibabacloud_config(region_id: str) -> Config:
    """Build SDK config with direct credentials, avoiding DefaultCredentialsProvider with unnecessary background scheduler."""
    timeout_kwargs = {"connect_timeout": 5_000, "read_timeout": 10_000}
    access_key_id = environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
    access_key_secret = environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    if access_key_id and access_key_secret:
        config = Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            region_id=region_id,
            **timeout_kwargs,
        )
        security_token = environ.get("ALIBABA_CLOUD_SECURITY_TOKEN")
        if security_token:
            config.security_token = security_token
        return config
    # SDK logs a full traceback per credential provider, caller reports the failure once.
    getLogger("credentials").setLevel(CRITICAL)
    return Config(credential=CredClient(), region_id=region_id, **timeout_kwargs)


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
    return EcsClient(_alibabacloud_config(region_id))


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
    return BssClient(_alibabacloud_config(region_id))


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
    if not response.body.data:
        print(f"No data in response: {response.to_map()}")
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
        if response.body.data:
            skus.extend(
                [
                    sku_price.to_map()
                    for sku_price in response.body.data.sku_price_page.sku_price_list
                ]
            )
        if vendor:
            vendor.progress_tracker.advance_task()
        if not response.body.data:
            break
    if vendor:
        vendor.progress_tracker.hide_task()
    return skus


def _get_server_sku_prices(vendor: Vendor) -> list[dict]:
    """Fetch server SKU prices using the `QuerySkuPriceList` API endpoint."""

    # example QuerySkuPriceList response:
    # {
    #     'Code': 'Success',
    #     'Data': {
    #         'SkuPricePage': {
    #             'NextPageToken': '2',
    #             'SkuPriceList': [
    #                 {
    #                     'CskuPriceList': [
    #                         {
    #                             'CskuCode': '63523368f2665ac9bdf26535c6410b65',
    #                             'Currency': 'USD',
    #                             'Price': '0.015',
    #                             'PriceMode': 'NORMAL_PRICE',
    #                             'PriceType': 'hourPrice',
    #                             'PriceUnit': 'USD',
    #                             'RangeList': [],
    #                             'UsageUnit': 'Set'
    #                         }
    #                     ],
    #                     'SkuCode': 'fd06adca15836eefceb723a91219f0a4',
    #                     'SkuFactorMap': {
    #                         'vm_region_no': 'us-west-ot7-a01',
    #                         'iooptimized': 'optimized',
    #                         'vm_os_kind': 'linux',
    #                         'instance_type': 'ecs.xn4.small'
    #                     }
    #                 }
    #             ],
    #             'TotalCount': 9491
    #         }
    #     },
    #     'Message': 'Successful!',
    #     'RequestId': '01A0CDD0-742A-3D9D-9618-207DDF19E404',
    #     'Success': True
    # }
    return _get_sku_prices(
        sku_type="server",
        extra_request_params={
            "price_entity_code": "instance_type",
            # filter for Linux prices only for now
            "price_factor_condition_map": {"vm_os_kind": ["linux"]},
        },
        vendor=vendor,
    )


def _get_storage_sku_prices(vendor: Vendor) -> list[dict]:
    """Fetch disk SKU prices using the `QuerySkuPriceList` API endpoint."""

    # example QuerySkuPriceList response:
    # {
    #     'Code': 'Success',
    #     'Data': {
    #         'SkuPricePage': {
    #             'NextPageToken': '2',
    #             'SkuPriceList': [
    #                 {
    #                     'CskuPriceList': [
    #                         {
    #                             'CskuCode': '8a4e8d6c9a94d3301d16d0210fae3dae',
    #                             'Currency': 'USD',
    #                             'Price': '0.0002',
    #                             'PriceMode': 'NORMAL_PRICE',
    #                             'PriceType': 'hourPrice',
    #                             'PriceUnit': 'USD/GB',
    #                             'RangeList': [],
    #                             'UsageUnit': 'GB'
    #                         }
    #                     ],
    #                     'SkuCode': 'aacf8bc78944707f354af04fba62badb',
    #                     'SkuFactorMap': {
    #                         'datadisk_category': 'cloud_ssd',
    #                         'vm_region_no': 'us-west-ot7-a01',
    #                         'datadisk_performance_level': 'NOT_EXIST'
    #                     }
    #                 }
    #             ],
    #             'TotalCount': 2800
    #         }
    #     },
    #     'Message': 'Successful!',
    #     'RequestId': '01A0CDD0-758B-3221-A830-0600CA3A1222',
    #     'Success': True
    # }
    return _get_sku_prices(
        sku_type="storage",
        extra_request_params={"price_entity_code": "datadisk"},
        vendor=vendor,
    )


def _get_traffic_sku_prices(vendor: Vendor) -> list[dict]:
    """Fetch traffic SKU prices using the `QuerySkuPriceList` API endpoint."""

    # example QuerySkuPriceList response:
    # {
    #     'Code': 'Success',
    #     'Data': {
    #         'SkuPricePage': {
    #             'NextPageToken': '2',
    #             'SkuPriceList': [
    #                 {
    #                     'CskuPriceList': [
    #                         {
    #                             'CskuCode': '4138936ae510f76ff504ff7d35d2d3dd',
    #                             'Currency': 'USD',
    #                             'Price': '0.123',
    #                             'PriceMode': 'STEP_ARRIVE',
    #                             'PriceType': 'usagePrice',
    #                             'PriceUnit': 'USD/GB',
    #                             'RangeList': [],
    #                             'UsageUnit': 'GB'
    #                         },
    #                         {
    #                             'CskuCode': '9bc498b33492f9ff7793b63f385a9de8',
    #                             'Currency': 'USD',
    #                             'Price': '0',
    #                             'PriceMode': 'STEP_ARRIVE',
    #                             'PriceType': 'hourPrice',
    #                             'PriceUnit': 'USD/GB',
    #                             'RangeList': [],
    #                             'UsageUnit': 'GB'
    #                         }
    #                     ],
    #                     'SkuCode': '75081341965736dd4a2b8b6782a3d195',
    #                     'SkuFactorMap': {
    #                         'vm_region_no': 'NOT_EXIST',
    #                         'isp_type': 'NOT_EXIST'
    #                     }
    #                 }
    #             ],
    #             'TotalCount': 63
    #         }
    #     },
    #     'Message': 'Successful!',
    #     'RequestId': '01A0CDD0-769E-30E2-A32E-096FB0867351',
    #     'Success': True
    # }
    return _get_sku_prices(
        sku_type="traffic",
        extra_request_params={"price_entity_code": "vm_flow_out"},
        vendor=vendor,
    )


def _get_region_availability_info(
    vendor: Vendor,
    instance_charge_type: str = "PostPaid",
    destination_resource: str = "InstanceType",
    resource_type: str = "instance",
    extra_request_params: Optional[dict] = None,
) -> dict[str, list[dict]]:
    """Fetch resource availability information using the `DescribeAvailableResource` API endpoint across all supported regions.

    Args:
        vendor: The Vendor object used for get region list and interacting with the progress tracker.
        instance_charge_type: The instance charge type, defaults to "PostPaid".
        destination_resource: The destination resource type, defaults to "InstanceType".
        resource_type: The resource type, defaults to "Instance".
        extra_request_params: Extra parameters to pass to the API request.

    Returns:
        A list of available resource info.
    """
    if extra_request_params is None:
        extra_request_params = {}
    region_availability_info: dict[str, list[dict]] = {}
    ecs_clients: dict[str, EcsClient] = _ecs_clients(vendor)

    @cachier(hash_func=jsoned_hash, separate_files=True)
    def fetch_region_availability(
        region_id: str,
        instance_charge_type: str,
        destination_resource: str,
        resource_type: str,
        extra_request_params: dict,
    ) -> tuple[str, list[dict]]:
        try:
            client = ecs_clients[region_id]
            resources = []
            request = DescribeAvailableResourceRequest(
                region_id=region_id,
                instance_charge_type=instance_charge_type,
                destination_resource=destination_resource,
                resource_type=resource_type,
                **extra_request_params,
            )
            runtime = RuntimeOptions()
            response = client.describe_available_resource_with_options(request, runtime)
            available_zones = response.body.available_zones
            if available_zones and available_zones.available_zone:
                # example DescribeAvailableResource response:
                # {
                #     'AvailableZones': {
                #         'AvailableZone': [
                #             {
                #                 'AvailableResources': {
                #                     'AvailableResource': [
                #                         {
                #                             'SupportedResources': {
                #                                 'SupportedResource': [
                #                                     {
                #                                         'Status': 'Available',
                #                                         'StatusCategory': 'WithStock',
                #                                         'Value': 'ecs.hfc9i.6xlarge'
                #                                     },
                #                                     # ...
                #                                 ]
                #                             },
                #                             'Type': 'InstanceType'
                #                         }
                #                     ]
                #                 },
                #                 'RegionId': 'eu-central-1',
                #                 'Status': 'Available',
                #                 'StatusCategory': 'WithStock',
                #                 'ZoneId': 'eu-central-1c'
                #             },
                #             # ...
                #         ]
                #     },
                #     'RequestId': '01A0CDD0-6AAD-34DA-8B8A-50E07069C1D5'
                # }
                resources = [
                    resource.to_map()
                    for resource in response.body.available_zones.available_zone
                ]
            return region_id, resources
        except Exception as e:
            logger.error(f"Failed to get availability info for region {region_id}: {e}")
            return region_id, []

    vendor.progress_tracker.start_task(
        name="Fetching server availability info", total=len(vendor.regions)
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(
            lambda region_id: fetch_region_availability(
                region_id,
                instance_charge_type,
                destination_resource,
                resource_type,
                extra_request_params,
            ),
            [r.region_id for r in vendor.regions],
        )
        for region_id, resources in results:
            region_availability_info[region_id] = resources
            vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()

    return region_availability_info


# Non-GPU accelerators reported in GPUSpec (standardized model name, lowercase),
# based on the GPUSpec values returned by DescribeInstanceTypes as of 2026-11
_NON_GPU_ACCELERATORS = {
    "vu9p": AcceleratorType.FPGA,
    "arria 10 gx 1150": AcceleratorType.FPGA,
    "agf027": AcceleratorType.FPGA,
    "t408": AcceleratorType.VPU,
    "alinpu 800": AcceleratorType.NPU,
    "ppu 810": AcceleratorType.NPU,
    "a910e": AcceleratorType.NPU,
    "a910x": AcceleratorType.NPU,
    "a910z": AcceleratorType.NPU,
}


def _accelerator_type(gpu_model: Optional[str], gpu_count: float):
    """Map the GPUSpec model to AcceleratorType.

    Defaults to GPU, as the API reports all accelerators in the GPU fields
    (GPUAmount, GPUSpec) and almost all of them are GPUs, so only the known
    non-GPU chips are listed in `_NON_GPU_ACCELERATORS`. New GPU models are
    covered without changes, while a new non-GPU chip needs to be added there.
    """
    if not gpu_count:
        return None
    return _NON_GPU_ACCELERATORS.get((gpu_model or "").lower(), AcceleratorType.GPU)


def _gpu_manufacturer_of_family(family: Optional[str]) -> Optional[str]:
    """Get the GPU manufacturer from the instance family name, if it tells.

    The "gn" families (and their "ebmgn" bare metal variants) are "compute
    optimized instances equipped with NVIDIA GPUs":
    https://help.aliyun.com/zh/ecs/user-guide/instance-specification-naming-and-classification
    """
    if (family or "").removeprefix("ecs.").startswith(("gn", "ebmgn")):
        return "NVIDIA"
    return None


def _get_resource_status_category(
    region_availability_info: dict[str, list[dict]],
    region_id: str,
    zone_id: str,
    server_id: str,
    resource_type: str = "InstanceType",
) -> Optional[str]:
    """Return AliCloud StatusCategory for a resource in a region/zone, if listed."""
    if not region_availability_info:
        return None

    zone_availability_info = next(
        (
            r
            for r in region_availability_info.get(region_id, [])
            if r.get("ZoneId") == zone_id
        ),
        None,
    )
    if not zone_availability_info:
        return None

    available_resource: list[dict] = zone_availability_info.get(
        "AvailableResources", {}
    ).get("AvailableResource", [])

    supported_resource: list[dict] = (
        next(
            (r for r in available_resource if r.get("Type") == resource_type),
            {},
        )
        .get("SupportedResources", {})
        .get("SupportedResource", [])
    )

    server_info = next(
        (r for r in supported_resource if r.get("Value") == server_id),
        None,
    )
    if not server_info:
        return None

    return server_info.get("StatusCategory")


def _get_spot_advices(
    vendor: Vendor, extra_request_params: Optional[dict] = None
) -> dict[str, list[dict]]:
    """Fetch spot advice information using the `DescribeSpotAdvice` API endpoint across all supported regions.
    Currently not used, keeping for possible future use.
    """
    if extra_request_params is None:
        extra_request_params = {}
    spot_advices: dict[str, list[dict]] = {}
    ecs_clients: dict[str, EcsClient] = _ecs_clients(vendor)

    def fetch_region_spot_advice(
        region_id: str, client: EcsClient
    ) -> tuple[str, list[dict]]:
        try:
            resources = []
            request = DescribeSpotAdviceRequest(
                region_id=region_id,
                **extra_request_params,
            )
            runtime = RuntimeOptions()
            response = client.describe_spot_advice_with_options(request, runtime)
            if response.body:
                spot_zones = response.body.available_spot_zones
                if spot_zones and spot_zones.available_spot_zone:
                    # example DescribeSpotAdvice response:
                    # {
                    #     'AvailableSpotZones': {
                    #         'AvailableSpotZone': [
                    #             {
                    #                 'AvailableSpotResources': {
                    #                     'AvailableSpotResource': [
                    #                         {
                    #                             'AverageSpotDiscount': 19,
                    #                             'InstanceType': 'ecs.g7.large',
                    #                             'InterruptRateDesc': '3-5%',
                    #                             'InterruptionRate': 3.61
                    #                         }
                    #                     ]
                    #                 },
                    #                 'ZoneId': 'eu-central-1a'
                    #             },
                    #             {
                    #                 'AvailableSpotResources': {
                    #                     'AvailableSpotResource': [
                    #                         {
                    #                             'AverageSpotDiscount': 19,
                    #                             'InstanceType': 'ecs.g7.large',
                    #                             'InterruptRateDesc': '0-3%',
                    #                             'InterruptionRate': 1
                    #                         }
                    #                     ]
                    #                 },
                    #                 'ZoneId': 'eu-central-1c'
                    #             }
                    #         ]
                    #     },
                    #     'RegionId': 'eu-central-1',
                    #     'RequestId': '01A0CDD0-6B65-3724-93F5-EF03BA926EB4'
                    # }
                    resources = [
                        spot_zone.to_map()
                        for spot_zone in spot_zones.available_spot_zone
                    ]
            return region_id, resources
        except Exception as e:
            logger.error(f"Failed to get spot info for region {region_id}: {e}")
            return region_id, []
        finally:
            vendor.progress_tracker.advance_task()

    vendor.progress_tracker.start_task(
        name="Fetching spot zone info", total=len(vendor.regions)
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(
            lambda args: fetch_region_spot_advice(*args),
            [(r.region_id, ecs_clients[r.region_id]) for r in vendor.regions],
        )
        for region_id, resources in results:
            spot_advices[region_id] = resources
    vendor.progress_tracker.hide_task()

    return spot_advices


def _get_instance_price(
    client: EcsClient,
    region_id: str,
    zone_id: str,
    instance_type: str,
    spot_strategy: str,
    resource_type: str = "instance",
) -> Optional[DescribePriceResponseBody]:
    """Fetch the price of a specific instance type in a specific region and zone.

    Args:
        client: The ECS client to use.
        region_id: The region ID.
        zone_id: The zone ID.
        instance_type: The instance type.
        spot_strategy: The spot strategy.
        resource_type: The resource type, defaults to "instance".
    Returns:
        The price response body.
    """

    # example DescribePrice response:
    # {
    #     'PriceInfo': {
    #         'Price': {
    #             'Currency': 'USD',
    #             'DetailInfos': {
    #                 'DetailInfo': [
    #                     {
    #                         'DiscountPrice': 0.0,
    #                         'OriginalPrice': 0.0,
    #                         'Resource': 'image',
    #                         'TradePrice': 0.0
    #                     },
    #                     {
    #                         'DiscountPrice': 0.0,
    #                         'OriginalPrice': 0.0,
    #                         'Resource': 'bandwidth',
    #                         'TradePrice': 0.0
    #                     },
    #                     {
    #                         'DiscountPrice': 0.0,
    #                         'OriginalPrice': 0.005024,
    #                         'Resource': 'systemDisk',
    #                         'TradePrice': 0.005024
    #                     },
    #                     {
    #                         'DiscountPrice': 0.08424,
    #                         'OriginalPrice': 0.104,
    #                         'Resource': 'instanceType',
    #                         'TradePrice': 0.01976
    #                     }
    #                 ]
    #             },
    #             'DiscountPrice': 0.08424,
    #             'OriginalPrice': 0.109024,
    #             'ReservedInstanceHourPrice': 0.0,
    #             'TradePrice': 0.024784
    #         },
    #         'Rules': {
    #             'Rule': [
    #                 {
    #                     'Description': 'Preemptible Instance discount',
    #                     'RuleId': 2
    #                 }
    #             ]
    #         }
    #     },
    #     'RequestId': '01A0CDD0-6D81-3C8C-AE07-A297D396D994'
    # }
    request = DescribePriceRequest(
        region_id=region_id,
        zone_id=zone_id,
        instance_type=instance_type,
        resource_type=resource_type,
        spot_strategy=spot_strategy,
    )
    runtime = RuntimeOptions()
    tried_system_disk = False
    tried_data_disk = False
    while True:
        try:
            response = client.describe_price_with_options(request, runtime)
            return response.body
        except Exception as e:
            if "InvalidSystemDiskCategory.ValueNotSupported" in str(e):
                if tried_system_disk:
                    return None
                request.system_disk = DescribePriceRequestSystemDisk(
                    category="cloud_essd"
                )
                tried_system_disk = True
                continue
            elif "InvalidDataDiskCategory.ValueNotSupported" in str(e):
                if tried_data_disk:
                    return None
                request.data_disks = [
                    DescribePriceRequestDataDisk(
                        category="cloud_essd",
                    )
                ]
                tried_data_disk = True
                continue
            elif "InvalidInstanceType.ValueNotSupported" in str(e):
                return None
            else:
                logger.warning(
                    f"Failed to get price for {instance_type} in {region_id}/{zone_id}: {e}"
                )
                return None


def _get_regions() -> list[dict]:
    """Fetch regions using the `DescribeRegions` API endpoint."""

    # example DescribeRegions response:
    # {
    #     'Regions': {
    #         'Region': [
    #             {
    #                 'LocalName': 'China (Qingdao)',
    #                 'RegionEndpoint': 'ecs.cn-qingdao.aliyuncs.com',
    #                 'RegionId': 'cn-qingdao'
    #             },
    #             # ...
    #         ]
    #     },
    #     'RequestId': '01A0CDD0-6911-30C1-9447-5E0405C4955B'
    # }
    request = DescribeRegionsRequest(accept_language="en-US")
    response = _ecs_client().describe_regions(request)
    return [region.to_map() for region in response.body.regions.region]


def _get_zones(client: EcsClient, region_id: str) -> list[dict]:
    """Fetch availability zones for a region using the `DescribeZones` API endpoint."""

    # example DescribeZones response:
    # {
    #     'RequestId': '01A0CDD0-6999-3D2B-B8EF-15E114D778BC',
    #     'Zones': {
    #         'Zone': [
    #             {
    #                 'AvailableDedicatedHostTypes': {
    #                     'DedicatedHostType': [
    #                         'ddh.ebmr6-inc',
    #                         # ...
    #                     ]
    #                 },
    #                 'AvailableDiskCategories': {
    #                     'DiskCategories': [
    #                         'cloud_efficiency',
    #                         # ...
    #                     ]
    #                 },
    #                 'AvailableInstanceTypes': {
    #                     'InstanceTypes': [
    #                         'ecs.c5-prio.16xlarge',
    #                         # ...
    #                     ]
    #                 },
    #                 'AvailableResourceCreation': {
    #                     'ResourceTypes': [
    #                         'VSwitch',
    #                         # ...
    #                     ]
    #                 },
    #                 'AvailableResources': {
    #                     'ResourcesInfo': [
    #                         {
    #                             'DataDiskCategories': {
    #                                 'supportedDataDiskCategory': [
    #                                     'cloud_efficiency',
    #                                     # ...
    #                                 ]
    #                             },
    #                             'InstanceGenerations': {
    #                                 'supportedInstanceGeneration': [
    #                                     'ecs-5',
    #                                     # ...
    #                                 ]
    #                             },
    #                             'InstanceTypeFamilies': {
    #                                 'supportedInstanceTypeFamily': [
    #                                     'ecs.i5e',
    #                                     # ...
    #                                 ]
    #                             },
    #                             'InstanceTypes': {
    #                                 'supportedInstanceType': [
    #                                     'ecs.u2i-c1m8.2xlarge',
    #                                     # ...
    #                                 ]
    #                             },
    #                             'IoOptimized': True,
    #                             'NetworkTypes': {
    #                                 'supportedNetworkCategory': [
    #                                     'vpc'
    #                                 ]
    #                             },
    #                             'SystemDiskCategories': {
    #                                 'supportedSystemDiskCategory': [
    #                                     'cloud_efficiency',
    #                                     # ...
    #                                 ]
    #                             }
    #                         }
    #                     ]
    #                 },
    #                 'AvailableVolumeCategories': {
    #                     'VolumeCategories': []
    #                 },
    #                 'DedicatedHostGenerations': {
    #                     'DedicatedHostGeneration': [
    #                         'ddh-5',
    #                         # ...
    #                     ]
    #                 },
    #                 'LocalName': 'Frankfurt Zone A',
    #                 'ZoneId': 'eu-central-1a',
    #                 'ZoneType': 'AvailabilityZone'
    #             },
    #             # ...
    #         ]
    #     }
    # }
    request = DescribeZonesRequest(region_id=region_id, accept_language="en-US")
    response = client.describe_zones(request)
    return response.body.to_map()["Zones"]["Zone"]


# Disk categories of the DescribeZones response mapped to our storage ids (see
# inventory_storages). The API only knows cloud_essd, not its performance levels
# (PL0-PL3): all four are assumed to be available. Neither the ESSD page nor the
# instance family overview restricts a PL by instance family: they only say that
# the instance type can cap the performance (e.g. PL1-PL3 cannot reach their peak on
# the economy e and the burstable t5/t6 families). Other categories (e.g.
# ephemeral_ssd, the local disk) are not block storage options in our schema.
# The overview says sn2ne supports only standard SSD and ultra disk (no ESSD), but
# the API returned cloud_essd for it in a live run (2026-10-27): not resolved.
# https://www.alibabacloud.com/help/en/ecs/user-guide/essds
# https://www.alibabacloud.com/help/en/ecs/user-guide/overview-of-instance-families
# https://www.alibabacloud.com/help/en/ecs/developer-reference/api-ecs-2014-05-26-describezones
_DISK_CATEGORY_TO_STORAGE_IDS = {
    "cloud_essd": [
        "cloud_essd-pl0",
        "cloud_essd-pl1",
        "cloud_essd-pl2",
        "cloud_essd-pl3",
    ],
    "cloud_ssd": ["cloud_ssd"],
    "cloud_efficiency": ["cloud_efficiency"],
    "cloud": ["cloud"],
}


def _parse_instance_type_disk_categories(zones: list[dict]) -> dict[str, list[str]]:
    """Map instance types to their data disk categories from DescribeZones zones.

    Each `AvailableResources.ResourcesInfo` item lists the instance types and the
    data disk categories that can be used together in that zone.
    """
    categories: dict[str, set[str]] = defaultdict(set)
    for zone in zones:
        for info in zone.get("AvailableResources", {}).get("ResourcesInfo", []):
            disks = info.get("DataDiskCategories", {}).get(
                "supportedDataDiskCategory", []
            )
            types = info.get("InstanceTypes", {}).get("supportedInstanceType", [])
            for instance_type in types:
                categories[instance_type].update(disks)
    return {k: sorted(v) for k, v in categories.items()}


def _get_instance_type_disk_categories(vendor: Vendor) -> dict[str, list[str]]:
    """Fetch the data disk categories of each instance type across all regions.

    Uses the `DescribeZones` API endpoint, one call per region, and returns the union
    of the categories seen in any zone.

    NOTE: checked against the live API on 2026-10-27: the response shape matches and
    98% of the ACTIVE servers got storage ids (the rest are old generations and the
    hpc8ae/hpc8i types). Whether the categories are accurate per instance type, and
    not only per zone, is not confirmed.
    """
    ecs_clients: dict[str, EcsClient] = _ecs_clients(vendor)

    @cachier(hash_func=jsoned_hash, separate_files=True)
    def fetch_region_disk_categories(region_id: str) -> dict[str, list[str]]:
        with sentry_capture_or_raise(vendor=vendor):
            zones = _get_zones(ecs_clients[region_id], region_id)
            return _parse_instance_type_disk_categories(zones)
        return {}

    vendor.progress_tracker.start_task(
        name="Fetching server disk categories", total=len(vendor.regions)
    )
    merged: dict[str, set[str]] = defaultdict(set)
    with ThreadPoolExecutor(max_workers=8) as executor:
        for region_categories in executor.map(
            fetch_region_disk_categories, [r.region_id for r in vendor.regions]
        ):
            for instance_type, categories in region_categories.items():
                merged[instance_type].update(categories)
            vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return {k: sorted(v) for k, v in merged.items()}


def _compatible_storage_ids(disk_categories: list[str]) -> list[str]:
    """Map the data disk categories of an instance type to our storage ids."""
    return [
        storage_id
        for category, storage_ids in _DISK_CATEGORY_TO_STORAGE_IDS.items()
        if category in disk_categories
        for storage_id in storage_ids
    ]


def _get_instance_types() -> list[dict]:
    """Fetch instance types using the `DescribeInstanceTypes` API endpoint."""

    # example DescribeInstanceTypes response:
    # {
    #     'InstanceTypes': {
    #         'InstanceType': [
    #             {
    #                 'Attributes': {
    #                     'Attribute': []
    #                 },
    #                 'Clock': {},
    #                 'CpuArchitecture': 'X86',
    #                 'CpuCoreCount': 4,
    #                 'CpuOptions': {},
    #                 'CpuSpeedFrequency': 0.0,
    #                 'CpuTurboFrequency': 0.0,
    #                 'DiskQuantity': 17,
    #                 'EnhancedNetwork': {},
    #                 'EniIpv6AddressQuantity': 0,
    #                 'EniPrivateIpAddressQuantity': 10,
    #                 'EniQuantity': 3,
    #                 'EniTotalQuantity': 3,
    #                 'EniTrunkSupported': False,
    #                 'EriQuantity': 0,
    #                 'GPUAmount': 1,
    #                 'GPUMemorySize': 16,
    #                 'GPUSpec': 'NVIDIA P100',
    #                 'InstanceBandwidthRx': 3072000,
    #                 'InstanceBandwidthTx': 3072000,
    #                 'InstanceCategory': 'Compute-optimized with GPU',
    #                 'InstanceFamilyLevel': 'EnterpriseLevel',
    #                 'InstancePpsRx': 300000,
    #                 'InstancePpsTx': 300000,
    #                 'InstanceTypeFamily': 'ecs.gn5',
    #                 'InstanceTypeId': 'ecs.gn5-c4g1.xlarge',
    #                 'JumboFrameSupport': False,
    #                 'LocalStorageAmount': 1,
    #                 'LocalStorageCapacity': 440,
    #                 'LocalStorageCategory': 'local_ssd_pro',
    #                 'MemorySize': 30.0,
    #                 'NetworkEncryptionSupport': False,
    #                 'NetworkInfo': {
    #                     'BandwidthWeighting': {}
    #                 },
    #                 'NvmeSupport': 'unsupported',
    #                 'PhysicalProcessorModel': '',
    #                 'PrimaryEniQueueNumber': 1,
    #                 'SecondaryEniQueueNumber': 1,
    #                 'SecurityOptions': {},
    #                 'SupportedBootModes': {
    #                     'SupportedBootMode': [
    #                         'BIOS'
    #                     ]
    #                 },
    #                 'TotalEniQueueQuantity': 3
    #             },
    #             {
    #                 'Attributes': {
    #                     'Attribute': []
    #                 },
    #                 'Clock': {},
    #                 'CpuArchitecture': 'ARM',
    #                 'CpuCoreCount': 32,
    #                 'CpuOptions': {
    #                     'Core': 32,
    #                     'CoreFactor': 2,
    #                     'ThreadsPerCore': 1
    #                 },
    #                 'CpuSpeedFrequency': 2.75,
    #                 'CpuTurboFrequency': 2.75,
    #                 'DiskQuantity': 17,
    #                 'EnhancedNetwork': {},
    #                 'EniIpv6AddressQuantity': 30,
    #                 'EniPrivateIpAddressQuantity': 30,
    #                 'EniQuantity': 8,
    #                 'EniTotalQuantity': 40,
    #                 'EniTrunkSupported': True,
    #                 'EriQuantity': 1,
    #                 'GPUAmount': 0,
    #                 'GPUSpec': '',
    #                 'InstanceBandwidthRx': 16384000,
    #                 'InstanceBandwidthTx': 16384000,
    #                 'InstanceCategory': 'General-purpose',
    #                 'InstanceFamilyLevel': 'EnterpriseLevel',
    #                 'InstancePpsRx': 5000000,
    #                 'InstancePpsTx': 5000000,
    #                 'InstanceTypeFamily': 'ecs.g8y',
    #                 'InstanceTypeId': 'ecs.g8yse.8xlarge',
    #                 'JumboFrameSupport': True,
    #                 'LocalStorageCategory': '',
    #                 'MaximumQueueNumberPerEni': 32,
    #                 'MemorySize': 128.0,
    #                 'NetworkEncryptionSupport': False,
    #                 'NetworkInfo': {
    #                     'BandwidthWeighting': {
    #                         'WeightingInfos': {
    #                             'WeightingInfo': [
    #                                 {
    #                                     'EbsBandwidth': 1500000,
    #                                     'Name': 'Default',
    #                                     'VpcBandwidth': 16384000,
    #                                     'VpcBurstBandwidth': 32768000
    #                                 },
    #                                 {
    #                                     'EbsBandwidth': 2500000,
    #                                     'Name': 'Ebs-L1',
    #                                     'VpcBandwidth': 8192000,
    #                                     'VpcBurstBandwidth': 24576000
    #                                 }
    #                             ]
    #                         }
    #                     }
    #                 },
    #                 'NvmeSupport': 'required',
    #                 'PhysicalProcessorModel': 'YiTian710',
    #                 'PrimaryEniQueueNumber': 32,
    #                 'QueuePairNumber': 15,
    #                 'SecondaryEniQueueNumber': 32,
    #                 'SecurityOptions': {},
    #                 'SupportedBootModes': {
    #                     'SupportedBootMode': [
    #                         'UEFI'
    #                     ]
    #                 },
    #                 'TotalEniQueueQuantity': 256
    #             }
    #         ]
    #     },
    #     'NextToken': '',
    #     'RequestId': '01A0CDD2-422C-39F2-80F0-DA15E54EE980'
    # }
    client = _ecs_client()
    additional_attributes = ["NetworkInfo.BandwidthWeighting"]
    request = DescribeInstanceTypesRequest(
        max_results=1000, additional_attributes=additional_attributes
    )
    response = client.describe_instance_types(request)
    instance_types = [
        instance_type.to_map()
        for instance_type in response.body.instance_types.instance_type
    ]
    while response.body.next_token:
        request = DescribeInstanceTypesRequest(
            max_results=1000,
            additional_attributes=additional_attributes,
            next_token=response.body.next_token,
        )
        response = client.describe_instance_types(request)
        for instance_type in response.body.instance_types.instance_type:
            instance_types.append(instance_type.to_map())
    return instance_types


@cache
def _warn_unknown_category(instance_type_id: str) -> None:
    """Warn about an instance type without category, once per type and run."""
    logger.warning(
        f"Missing Alibaba Cloud InstanceCategory of {instance_type_id}, "
        "leaving family empty."
    )


# `InstanceCategory` spelling of the API changed to match the other vendors: hyphens
# are replaced by a space and the word after is capitalized (General-purpose ->
# General Purpose, Compute-optimized with GPU -> Compute Optimized with GPU), plus the
# HPC spelling.
_CATEGORY_SPELLING = {
    "High Performance Compute": "High Performance Computing",
}


def _category_spelling(category: str) -> str:
    if category in _CATEGORY_SPELLING:
        return _CATEGORY_SPELLING[category]
    return sub(r"-(\w)", lambda match: " " + match.group(1).upper(), category)


# The API returns no `InstanceCategory` for these retired families, so the category
# comes from the docs, written as the API does for the current families (`Shared` for
# the shared n4, mn4, e4 etc., `High Clock Speed` for the hfc/hfg/hfr families, and the
# category of the sn1ne / sn2ne). The old "Series I" families (t1, s1, s2, s3, m1, m2,
# c1, c2) and u0 are not categorized in the docs, so they are left empty.
# https://www.alibabacloud.com/help/en/ecs/user-guide/retired-instance-types
# https://www.alibabacloud.com/help/en/ecs/user-guide/shared-instance-families
_RETIRED_FAMILY_CATEGORY = {
    "ecs.sn1": "Compute Optimized",
    "ecs.sn2": "General Purpose",
    "ecs.c4": "High Clock Speed",
    "ecs.ce4": "High Clock Speed",
    "ecs.cm4": "High Clock Speed",
    "ecs.n1": "Shared",
    "ecs.n2": "Shared",
    "ecs.e3": "Shared",
}


def _instance_category(instance_type: dict) -> Optional[str]:
    """Family of an instance type: the `InstanceCategory` as returned by the API.

    E.g. General Purpose, Memory Optimized, Compute Optimized with GPU. Documented at
    <https://www.alibabacloud.com/help/en/ecs/developer-reference/api-ecs-2014-05-26-describeinstancetypes>.
    Only the spelling is unified with the other vendors (no hyphens, and High
    Performance Computing), see `_category_spelling`. A few retired families without
    category in the API use the one of the docs, see `_RETIRED_FAMILY_CATEGORY`.
    Returns None if missing, so no family is guessed.
    """
    if category := instance_type.get("InstanceCategory"):
        return _category_spelling(category)
    if category := _RETIRED_FAMILY_CATEGORY.get(
        instance_type.get("InstanceTypeFamily")
    ):
        return category
    _warn_unknown_category(instance_type.get("InstanceTypeId"))
    return None


def _gpu_memory_by_spec(instance_types: list[dict]) -> dict[str, float]:
    """Per-GPU memory (GiB) by `GPUSpec`, where all instance types reporting it agree.

    Some instance types miss `GPUMemorySize` (e.g. `ecs.gn7s` with NVIDIA A30),
    while others with the same GPU report it. Fractional GPUs have their own
    `GPUSpec` (e.g. "NVIDIA A10*1/2"), so they do not mix with whole GPUs.
    """
    sizes = defaultdict(set)
    for instance_type in instance_types:
        if instance_type.get("GPUMemorySize") and instance_type.get("GPUSpec"):
            sizes[instance_type["GPUSpec"]].add(float(instance_type["GPUMemorySize"]))
    return {spec: size.pop() for spec, size in sizes.items() if len(size) == 1}


def _determine_cpu_allocation_type(instance_type: dict) -> CpuAllocation:
    """Determine the CPU allocation type based on the instance type properties.

    Args:
        instance_type: The instance type dictionary.

    Returns:
        The CPU allocation type.
    """
    instance_category = instance_type.get("InstanceCategory", "")
    baseline_credit = instance_type.get("BaselineCredit", 0)
    if baseline_credit > 0:
        return CpuAllocation.BURSTABLE
    if instance_category == "Shared":
        return CpuAllocation.SHARED
    return CpuAllocation.DEDICATED


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
    "cn-hangzhou-acdr-ut-3": {
        "city": "Hangzhou",
        "lat": 30.2741,
        "lon": 120.1551,
        "country_id": "CN",
        "founding_year": 2026,
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
    "cn-zhongwei": {
        "city": "Zhongwei",
        "lat": 37.5000,
        "lon": 105.1929,
        "country_id": "CN",
        "founding_year": 2026,
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
    "ap-southeast-8": {
        "city": "Johor",
        "lat": 1.4927,
        "lon": 103.7414,
        "country_id": "MY",
        "founding_year": 2025,
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
    # -------- South America --------
    "sa-east-1": {
        "city": "Sao Paulo",
        "lat": -23.5505,
        "lon": -46.6333,
        "country_id": "BR",
        "founding_year": 2026,
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
    "eu-west-2": {
        "city": "Paris",
        "lat": 48.8566,
        "lon": 2.3522,
        "country_id": "FR",
        "founding_year": 2026,
    },
    # https://www.alibabacloud.com/en/press-room/first-public-cloud-region-in-the-netherlands
    "eu-west-3": {
        "city": "Amsterdam",
        "lat": 52.3676,
        "lon": 4.9041,
        "country_id": "NL",
        "founding_year": 2026,
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
    regions = _get_regions()

    items = []
    for region in regions:
        with sentry_capture_or_raise(vendor=vendor):
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

    @cachier(hash_func=jsoned_hash, separate_files=True)
    def fetch_zones_for_region(region_id):
        """Worker function to fetch zones for a single region."""
        zone_items = []

        def on_error():
            region_to_set_inactive = get_region_by_id(region_id, vendor)
            if region_to_set_inactive:
                region_to_set_inactive.status = Status.INACTIVE
                vendor.log(
                    f"Marking region {region_id} as inactive due to error "
                    "while fetching availability zones.",
                    WARN,
                )

        with sentry_capture_or_raise(vendor=vendor, on_error=on_error):
            for zone in _get_zones(clients[region_id], region_id):
                zone_items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": region_id,
                        "zone_id": zone.get("ZoneId"),
                        "name": zone.get("LocalName"),
                        "api_reference": zone.get("ZoneId"),
                        "display_name": zone.get("LocalName"),
                    }
                )
        vendor.progress_tracker.advance_task()
        return zone_items

    with ThreadPoolExecutor(max_workers=8) as executor:
        items = executor.map(
            fetch_zones_for_region, [r.region_id for r in vendor.regions]
        )
    items = list(chain.from_iterable(items))
    vendor.progress_tracker.hide_task()
    return items


def inventory_servers(vendor):
    """List all server types at Alibaba Cloud using the `DescribeInstanceTypes` API endpoint.

    Lifecycle (`DescribeAvailableResource` `StatusCategory`): WithStock and
    WithoutStock (out of stock, but replenished) -> ACTIVE,
    ClosedWithStock -> PLANNED_FOR_RETIREMENT, ClosedWithoutStock -> RETIRED;
    missing in availability response -> INACTIVE.
    """
    instance_types = _get_instance_types()
    gpu_memory_by_spec = _gpu_memory_by_spec(instance_types)

    region_availability_info: dict[str, list[dict]] = _get_region_availability_info(
        vendor
    )
    disk_categories = _get_instance_type_disk_categories(vendor)
    no_storage_ids: list[str] = []

    CPU_ARCH_MAP = {"X86": CpuArchitecture.X86_64, "ARM": CpuArchitecture.ARM64}
    STORAGE_CATEGORY_MAP = {
        "": None,
        "local_ssd_pro": StorageType.SSD,
        "local_hdd_pro": StorageType.HDD,
    }

    def drop_zero_value(x):
        return None if x == 0 else x

    items = []

    def _parse_network_fields(instance_type: dict) -> dict:
        network_fields = {
            "network_speed_baseline": drop_zero_value(
                instance_type.get("InstanceBandwidthRx", 0) / 1024 / 1000
            ),
            "network_speed_max": None,
            "network_storage_speed_baseline": None,
            "network_storage_speed_max": None,
        }
        if not instance_type.get("NetworkInfo", {}).get("BandwidthWeighting"):
            return network_fields
        weighting_infos = (
            instance_type.get("NetworkInfo", {})
            .get("BandwidthWeighting", {})
            .get("WeightingInfos", {})
            .get("WeightingInfo", [])
        )
        network_speeds = []
        network_storage_speeds = []
        for weighting_info in weighting_infos:
            if weighting_info.get("VpcBandwidth"):
                network_speeds.append(weighting_info.get("VpcBandwidth") / 1024 / 1000)
            if weighting_info.get("VpcBurstBandwidth"):
                network_speeds.append(
                    weighting_info.get("VpcBurstBandwidth") / 1024 / 1000
                )
            if weighting_info.get("EbsBandwidth"):
                network_storage_speeds.append(
                    round(
                        weighting_info.get("EbsBandwidth") * 8 / 1_000_000
                    )  # Bps -> Gbps
                )
            if weighting_info.get("EbsBurstBandwidth"):
                network_storage_speeds.append(
                    round(
                        weighting_info.get("EbsBurstBandwidth") * 8 / 1_000_000
                    )  # Bps -> Gbps
                )
        network_fields["network_speed_max"] = (
            max(network_speeds) if network_speeds else None
        )
        network_fields["network_storage_speed_baseline"] = (
            min(network_storage_speeds) if network_storage_speeds else None
        )
        network_fields["network_storage_speed_max"] = (
            max(network_storage_speeds) if network_storage_speeds else None
        )
        return network_fields

    for instance_type in instance_types:
        # e.g. ecs.g7, the instance family called series in our schema
        series = instance_type.get("InstanceTypeFamily")
        family = _instance_category(instance_type)
        vcpus = instance_type.get("CpuCoreCount")
        cpu_model = instance_type.get("PhysicalProcessorModel")
        memory_size_mb = int((instance_type.get("MemorySize") * 1024))
        memory_size_gb = (
            memory_size_mb // 1024
            if memory_size_mb >= 1024
            else round(memory_size_mb / 1024, 2)
        )
        storage_size = int(
            instance_type.get("LocalStorageAmount", 0)
            * instance_type.get("LocalStorageCapacity", 0)
            # convert GiB to GB
            * 1024**3
            / 1000**3
        )
        storage_type = STORAGE_CATEGORY_MAP[instance_type["LocalStorageCategory"]]
        gpu_count = _standardize_gpu_count(
            instance_type["GPUSpec"], instance_type.get("GPUAmount", 0)
        )
        # GPUMemorySize contains total memory for fractional or single GPUs, but per-GPU memory for multiple GPUs
        gpu_memory_gib = instance_type.get("GPUMemorySize") or (
            gpu_memory_by_spec.get(instance_type["GPUSpec"]) if gpu_count else 0
        )
        if gpu_memory_gib is None:
            # unknown: leave it to the inspector instead of storing 0
            gpu_memory_per_gpu = gpu_memory_total = None
        else:
            gpu_memory_per_gpu = gpu_memory_gib * 1024  # GiB -> MiB
            gpu_memory_total = (
                gpu_count * gpu_memory_per_gpu if gpu_count >= 1 else gpu_memory_per_gpu
            )
        gpu_model = _standardize_gpu_model(instance_type["GPUSpec"])
        gpu_family = None
        gpu_manufacturer = None
        if gpu_model:
            # AliCloud uses some internal GPU model names in GPUSpec (e.g. G49/G49E, GPU H/H-e, L20N).
            # https://help.aliyun.com/zh/functioncompute/fc/support/some-gpu-card-types-do-not-provide-sla-commitment-statement
            if gpu_model.startswith("G49"):
                gpu_model = None
                gpu_family = "Ada Lovelace"
                gpu_manufacturer = "NVIDIA"
            # these instances maybe use Hopper GPUs, but we have no proof yet
            elif gpu_model.startswith("GPU H"):
                gpu_model = None
            elif gpu_model == "L20":
                gpu_family = "Ada Lovelace"
                gpu_manufacturer = "NVIDIA"
            # https://www.alibabacloud.com/help/en/ecs/user-guide/elastic-bare-metal-server-overview
            elif gpu_model == "L20N":
                gpu_model = None
                gpu_family = "Blackwell"
                gpu_manufacturer = "NVIDIA"
            # https://www.alibabacloud.com/help/en/ecs/user-guide/gpu-accelerated-compute-optimized-and-vgpu-accelerated-instance-families-1
            elif gpu_model == "vGPU8":
                gpu_model = None
                gpu_family = "Ada Lovelace"
                gpu_manufacturer = "NVIDIA"
            # the GPU architecture instead of the model
            elif gpu_model == "Lovelace":
                gpu_model = None
                gpu_family = "Ada Lovelace"
                gpu_manufacturer = "NVIDIA"
            # "Blackwell series: NVIDIA G59" in the above SLA statement
            elif gpu_model == "G59":
                gpu_family = "Blackwell"
                gpu_manufacturer = "NVIDIA"
        if gpu_count and not gpu_manufacturer:
            gpu_manufacturer = _gpu_manufacturer_of_family(family)
        description_parts = [
            f"{vcpus} vCPUs",
            f"{memory_size_gb} GiB RAM",
            f"{storage_size} GB {storage_type.value if storage_type else ''} storage",
            (
                f"{gpu_count}x{gpu_model}"
                + (f" {gpu_memory_gib:g} GiB VRAM" if gpu_memory_gib else "")
                if gpu_count and gpu_model
                else None
            ),
        ]
        server_id = instance_type.get("InstanceTypeId")
        # no entry in DescribeZones: unknown (None), not "no compatible storage" ([])
        if server_id in disk_categories:
            compatible_storage_ids = _compatible_storage_ids(disk_categories[server_id])
        else:
            compatible_storage_ids = None
            no_storage_ids.append(server_id)
        description = f"{series} family ({', '.join(filter(None, description_parts))})"
        status_categories = {
            category
            for region_id, zones in region_availability_info.items()
            for zone_info in zones
            if (
                category := _get_resource_status_category(
                    region_availability_info,
                    region_id,
                    zone_info.get("ZoneId"),
                    server_id,
                )
            )
        }
        status = server_status_from_availability_categories(
            status_categories,
            _ALICLOUD_STATUS_CATEGORY_TO_SERVER_LIFECYCLE,
        )

        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "server_id": server_id,
                "name": server_id,
                "api_reference": server_id,
                # https://www.pulumi.com/registry/packages/alicloud/api-docs/ecs/instance/
                "api_reference_object": {"instance_type": server_id},
                "display_name": server_id,
                "description": description,
                "family": family,
                "series": series,
                "vcpus": vcpus,
                "hypervisor": "KVM",
                "cpu_allocation": _determine_cpu_allocation_type(instance_type),
                "cpu_speed": drop_zero_value(instance_type.get("CpuSpeedFrequency")),
                "cpu_architecture": CPU_ARCH_MAP[instance_type.get("CpuArchitecture")],
                "cpu_manufacturer": _extract_manufacturer(cpu_model),
                "cpu_family": _extract_family(cpu_model),
                "cpu_model": _standardize_cpu_model(cpu_model),
                "cpu_flags": [],
                "cpus": [],
                "memory_amount": memory_size_mb,
                "memory_generation": None,
                "memory_speed": None,
                "memory_ecc": None,
                "accelerator_count": gpu_count,
                "accelerator_memory_min": gpu_memory_per_gpu,
                "accelerator_memory_total": gpu_memory_total,
                "accelerator_type": _accelerator_type(gpu_model, gpu_count),
                # TODO fill in from GPUSpec? or just let the inspector fill it in?
                "accelerator_manufacturer": gpu_manufacturer,
                "accelerator_family": gpu_family,
                "accelerator_model": gpu_model,
                "accelerators": [],
                "storage_size": storage_size,
                "storage_type": storage_type,
                "storages": [],
                "compatible_storage_ids": compatible_storage_ids,
                # TODO: have to implement manual mapping here too, no detailed
                # network info available for every instance type in API response
                **_parse_network_fields(instance_type),
                "inbound_traffic": 0,
                "outbound_traffic": 0,
                "ipv4": 0,
                "status": status,
            }
        )

    if no_storage_ids:
        vendor.log(
            f"No known block storage for {len(no_storage_ids)} instance types "
            f"(e.g. {', '.join(no_storage_ids[:5])}), leaving compatible storage unknown.",
            level=WARN,
        )
    return items


def inventory_server_prices(vendor):
    """Fetch server pricing and regional availability using the `QuerySkuPriceListRequest` API endpoint.

    Alternative approach could be looking at <https://g.alicdn.com/aliyun/ecs-price-info-intl/2.0.375/price/download/instancePrice.json>.
    """
    skus = _get_server_sku_prices(vendor)

    items = []
    unsupported_regions = set()
    region_availability_info: dict[str, list[dict]] = _get_region_availability_info(
        vendor
    )

    for sku in skus:
        sku_region_id = sku["SkuFactorMap"]["vm_region_no"]
        region = get_region_by_id(sku_region_id, vendor)
        if not region:
            unsupported_regions.add(sku_region_id)
            continue
        for zone in region.zones:
            server_id = sku.get("SkuFactorMap", {}).get("instance_type")
            category = _get_resource_status_category(
                region_availability_info,
                region.region_id,
                zone.zone_id,
                server_id,
            )
            mapped = _ALICLOUD_STATUS_CATEGORY_TO_SERVER_STATUS.get(
                category or "", Status.INACTIVE
            )
            status = Status.ACTIVE if mapped.is_orderable else Status.INACTIVE

            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.region_id,
                    "zone_id": zone.zone_id,
                    "server_id": server_id,
                    "operating_system": sku.get("SkuFactorMap").get("vm_os_kind"),
                    "allocation": Allocation.ONDEMAND,
                    "unit": PriceUnit.HOUR,
                    "price": float(sku.get("CskuPriceList")[0].get("Price")),
                    "price_upfront": 0,
                    "price_tiered": [],
                    "currency": sku.get("CskuPriceList")[0].get("Currency"),
                    "status": status,
                }
            )
    for unsupported_region in unsupported_regions:
        vendor.log(f"Found non-supported region: {unsupported_region}", level=WARN)
    overall = Counter()
    status_by_region: dict[str, Counter] = defaultdict(Counter)
    for item in items:
        status = item["status"]
        status_by_region[item["region_id"]][status] += 1
        overall[status] += 1
    for region_id in sorted(status_by_region):
        counts = status_by_region[region_id]
        vendor.log(
            f"{region_id}: Found {counts[Status.ACTIVE]} ACTIVE and "
            f"{counts[Status.INACTIVE]} INACTIVE on-demand server prices",
            level=INFO,
        )
    vendor.log(
        f"OVERALL: Found {overall[Status.ACTIVE]} ACTIVE and "
        f"{overall[Status.INACTIVE]} INACTIVE on-demand server prices",
        level=INFO,
    )
    return items


def inventory_server_prices_spot(vendor):
    """Fetch spot instance pricing by time-based sampling of on-demand instances per region.

    Each region worker fetches spot prices for a random sample of instances within sample_time,
    adapting to different response times, parallelized across regions.
    """
    sample_time = 120  # seconds

    ecs_clients: dict[str, EcsClient] = _ecs_clients(vendor)

    ondemand_instances = defaultdict(list)
    for server_price in vendor.server_prices:
        if (
            server_price.allocation == Allocation.ONDEMAND
            and server_price.status == Status.ACTIVE
        ):
            ondemand_instances[server_price.region_id].append(
                (server_price.zone_id, server_price.server_id)
            )

    if not ondemand_instances:
        logger.error("No active ondemand instances found")
        return []

    for region_id in ondemand_instances:
        shuffle(ondemand_instances[region_id])

    def fetch_spot_instance_price(
        region_id: str, zone_instance_list: list[tuple[str, str]], client: EcsClient
    ):
        spot_instances = []
        start_time = time()

        for zone_id, instance_type in zone_instance_list:
            try:
                # Check if time limit exceeded
                elapsed = time() - start_time
                if elapsed >= sample_time:
                    break

                price_response_body: DescribePriceResponseBody = _get_instance_price(
                    region_id=region_id,
                    zone_id=zone_id,
                    instance_type=instance_type,
                    client=client,
                    spot_strategy="SpotAsPriceGo",
                )

                if not price_response_body:
                    continue

                if not next(
                    (
                        r
                        for r in price_response_body.price_info.rules.rule
                        if r.description == "Preemptible Instance discount"
                    ),
                    None,
                ):
                    continue

                trade_price = next(
                    (
                        p.trade_price
                        for p in price_response_body.price_info.price.detail_infos.detail_info
                        if p.resource == "instanceType"
                    ),
                    None,
                )

                if not trade_price:
                    continue

                spot_instances.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": region_id,
                        "zone_id": zone_id,
                        "server_id": instance_type,
                        "operating_system": "linux",
                        "allocation": Allocation.SPOT,
                        "unit": PriceUnit.HOUR,
                        "price": float(trade_price),
                        "price_upfront": 0,
                        "price_tiered": [],
                        "currency": price_response_body.price_info.price.currency,
                        "status": Status.ACTIVE,
                    }
                )
            except AttributeError:
                continue
            except Exception as e:
                logger.error(
                    f"Failed to get spot price for {instance_type} in {region_id}/{zone_id}: {e}"
                )
                continue
            finally:
                vendor.progress_tracker.advance_task()

        if not spot_instances:
            logger.info(f"No spot prices found in region {region_id}")

        return spot_instances

    vendor.progress_tracker.start_task(
        name=f"Fetching spot instance prices for {sample_time} second(s)",
        total=sum(len(zil) for zil in ondemand_instances.values()),
    )

    with ThreadPoolExecutor(max_workers=len(ondemand_instances)) as executor:
        items = executor.map(
            lambda args: fetch_spot_instance_price(*args),
            [
                (region_id, zone_instance_list, ecs_clients[region_id])
                for region_id, zone_instance_list in ondemand_instances.items()
            ],
        )
    items = list(chain.from_iterable(items))

    vendor.progress_tracker.hide_task()

    vendor.set_table_rows_active(
        ServerPrice,
        ServerPrice.allocation == Allocation.SPOT,
        ServerPrice.observed_at >= datetime.now() - timedelta(days=30),
    )

    return items


def inventory_storages(vendor):
    """List all block storage offerings.

    Data sources:

    - <https://www.alibabacloud.com/help/en/ecs/user-guide/essds>
    - <https://www.alibabacloud.com/help/en/ecs/developer-reference/api-ecs-2014-05-26-createdisk>
    - <https://www.alibabacloud.com/help/en/ecs/user-guide/block-storage-performance>

    Capacity ranges are specified in GiB in the Alibaba Cloud documentation and are
    converted to GB here. Throughput values are in MB/s as per the documentation.
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
            "max_tp": 180,
            "info": "Enterprise SSD with performance level 0.",
        },
        {
            "name": "cloud_essd-pl1",
            "min_size": 20,
            "max_size": 65536,
            "max_iops": 50000,
            "max_tp": 350,
            "info": "Enterprise SSD with performance level 1.",
        },
        {
            "name": "cloud_essd-pl2",
            "min_size": 461,
            "max_size": 65536,
            "max_iops": 100000,
            "max_tp": 750,
            "info": "Enterprise SSD with performance level 2.",
        },
        {
            "name": "cloud_essd-pl3",
            "min_size": 1261,
            "max_size": 65536,
            "max_iops": 1000000,
            "max_tp": 4000,
            "info": "Enterprise SSD with performance level 3.",
        },
        {
            "name": "cloud_ssd",
            "min_size": 20,
            "max_size": 32768,
            "max_iops": 25000,
            "max_tp": 300,
            "info": "Standard SSD.",
        },
        {
            "name": "cloud_efficiency",
            "min_size": 20,
            "max_size": 32768,
            "max_iops": 5000,
            "max_tp": 140,
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
                "min_size": round(disk["min_size"] * _GIB_TO_GB),
                "max_size": round(disk["max_size"] * _GIB_TO_GB),
            }
        )
    return items


def inventory_storage_prices(vendor):
    """Fetch server prices using the `QuerySkuPriceListRequest` API endpoint."""
    skus = _get_storage_sku_prices(vendor)

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
        storage_price = float(sku["CskuPriceList"][0]["Price"])
        price_type = sku["CskuPriceList"][0]["PriceType"]
        if price_type == "hourPrice":
            storage_price = storage_price * _HOURS_PER_MONTH
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.region_id,
                "storage_id": storage_id,
                "unit": PriceUnit.GB_MONTH,
                "price": storage_price,
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
    skus = _get_traffic_sku_prices(vendor)
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
                "price": float(price["Price"]),
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


# ##############################################################################
# Managed databases: ApsaraDB RDS for PostgreSQL

_RDS_ENGINE = "PostgreSQL"
# pay-as-you-go primary instances on the international site
_RDS_COMMODITY_CODE = "bards_intl"

# RDS editions, called `category` in the RDS APIs (matched lowercased, as the
# casing differs between endpoints: e.g. "cluster" in `DescribeAvailableZones`
# and "Cluster" in `ListClasses`). An instance type belongs to a single edition,
# shown by its suffix: `.1`/`.1m` Basic, `.2c`/`.2m` High-availability and `.xc`
# Cluster Edition.
#
# - https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/product-editions/
# - https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/rds-cluster-edition
# - https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/features-of-apsaradb-rds-for-postgresql
# - https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/rds-for-postgresql-read-only-instances
_RDS_EDITIONS: dict[str, dict] = {
    # single node, no read-only instances, no log backups (point-in-time restore)
    "basic": {
        "name": "Basic Edition",
        "category": "Basic",
        "billed_nodes": 1,
        "ha": [DatabaseHaLevel.NONE],
        "ha_strategy": DatabaseHaStrategy.NONE,
        "max_read_replicas": 0,
        "continuous_backups": 0,
    },
    # primary and a not accessible secondary node, in the same or in another zone
    # for the same price; the instance type price covers both nodes; up to 32
    # read-only instances with cloud disks
    "ha": {
        "name": "High-availability Edition",
        "category": "HighAvailability",
        "billed_nodes": 1,
        "ha": [DatabaseHaLevel.MULTI_ZONE, DatabaseHaLevel.SINGLE_ZONE],
        "ha_strategy": DatabaseHaStrategy.PASSIVE_STANDBY,
        "max_read_replicas": 32,
        "continuous_backups": 730,
    },
    # primary and 1 to 8 readable secondary nodes, in up to as many zones as
    # nodes; instance type and storage are billed per node, so the prices are
    # stored for the smallest cluster of 2 nodes
    "cluster": {
        "name": "Cluster Edition",
        "category": "cluster",
        "billed_nodes": 2,
        "ha": [DatabaseHaLevel.MULTI_ZONE, DatabaseHaLevel.SINGLE_ZONE],
        "ha_strategy": DatabaseHaStrategy.READABLE_CLUSTER,
        "max_read_replicas": 8,
        "continuous_backups": 730,
    },
}
_RDS_CATEGORY_TO_EDITION = {
    edition["category"].lower(): edition_id
    for edition_id, edition in _RDS_EDITIONS.items()
}

# Cloud disk types of RDS for PostgreSQL, with sizes in GiB and the baseline
# performance limits of the disks (the limits of an instance also depend on the
# storage size and the instance type). The phased-out local and standard SSDs
# (`local_ssd`, `cloud_ssd`) are not tracked.
#
# - https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/primary-apsaradb-rds-for-postgresql-instance-types
# - https://www.alibabacloud.com/help/en/ecs/user-guide/essds
_RDS_STORAGE_TYPES: dict[str, dict] = {
    "cloud_essd": {
        "name": "ESSD PL1",
        "description": "Enterprise SSD with performance level 1",
        "min_size": 20,
        "max_size": 64000,
        "max_iops": 50000,
        "max_throughput": 350,
    },
    "cloud_essd2": {
        "name": "ESSD PL2",
        "description": "Enterprise SSD with performance level 2",
        "min_size": 500,
        "max_size": 64000,
        "max_iops": 100000,
        "max_throughput": 750,
    },
    "cloud_essd3": {
        "name": "ESSD PL3",
        "description": "Enterprise SSD with performance level 3",
        "min_size": 1500,
        "max_size": 64000,
        "max_iops": 1000000,
        "max_throughput": 4000,
    },
    "cloud_auto": {
        "name": "Premium ESSD",
        "description": (
            "Premium ESSD with the baseline performance of ESSD PL1, "
            "and optional I/O burst billed separately"
        ),
        "min_size": 10,
        "max_size": 64000,
        "max_iops": 50000,
        "max_throughput": 350,
    },
}

# `ClassGroup` of `ListClasses` (only returned in Chinese) to the instance family
# in the naming of the English documentation.
_RDS_CLASS_GROUP_TO_FAMILY = {
    "通用型": "General Purpose",
    "独享套餐": "Dedicated",
    "Intel SGX 安全增强": "Security Enhanced",
}
# notes in the `MemoryClass` of `ListClasses`: "end of sale soon" and "end of sale"
_RDS_END_OF_SALE_SOON = "即将停售"
_RDS_END_OF_SALE = "已停售"


def _rds_storage_id(storage_type: str, edition_id: str) -> str:
    """Database storage id of a cloud disk type in an RDS edition.

    The storage price of the same disk type depends on the edition (e.g. ESSD
    PL1 is 0.0006 USD/GB/hour in the Basic and 0.001 USD/GB/hour in the
    High-availability Edition in Frankfurt), so those are different products.

    The alternative is a single id per disk type (e.g. `cloud_essd`) with the
    single-node price of the Basic Edition, as done for `AWS` and `GCP`, as
    `DatabaseStoragePrice` has no edition or HA dimension. That would need only
    4 instead of 12 storages, but the storage cost of the other editions could
    not be computed from it: e.g. 100 GB ESSD PL1 in Frankfurt is 43.8 USD/month
    in the Basic Edition, while 73 USD/month in the High-availability Edition
    (1.67x, covering both nodes), and 58.4 USD/month for a 2-node cluster (0.67x
    per node).
    """
    return f"{storage_type}-{edition_id}"


@cache
def _rds_client(region_id: str) -> RdsClient:
    """Create an Alibaba Cloud RDS client, see `_ecs_client` on the credentials."""
    return RdsClient(_alibabacloud_config(region_id))


def _rds_clients(vendor: Vendor) -> dict[str, RdsClient]:
    """Create the RDS clients of all active regions in the main thread, see `_ecs_clients`."""
    return {
        region.region_id: _rds_client(region.region_id)
        for region in vendor.regions
        if region.status == Status.ACTIVE
    }


# transient network errors of the RDS endpoints worth retrying
_RDS_TRANSIENT_ERRORS = (
    "Throttling",
    "Connection aborted",
    "Connection reset",
    "Read timed out",
    "Max retries exceeded",
)


def _rds_call(method, request, attempts: int = 15) -> dict:
    """Call an RDS API method, waiting out the flow control of the endpoint.

    E.g. `DescribeAvailableClasses` allows only around 2 requests per 13
    seconds, counted separately for each region, so the wait grows up to that.
    Connection resets and timeouts (seen at the endpoints far from the client)
    are retried as well.
    """
    for attempt in range(attempts):
        try:
            return method(request, RuntimeOptions()).body.to_map()
        except Exception as e:
            transient = any(error in str(e) for error in _RDS_TRANSIENT_ERRORS)
            if not transient or attempt == attempts - 1:
                raise
            sleep(min(2 + attempt, 13))


def _parse_rds_available_zones(available_zones: list[dict]) -> dict[str, dict]:
    """Collect the PostgreSQL versions and cloud disk types offered per edition and zone.

    The multi-zone ids (e.g. `eu-central-1MAZ1(a,b)`) are skipped, as these are
    pairs of zones listed on their own as well.

    Returns:
        `{edition_id: {zone_id: {"versions": [...], "storage_types": [...]}}}`
    """
    offers: dict[str, dict] = {}
    for zone in available_zones:
        zone_id = zone.get("ZoneId") or ""
        if not zone_id or "MAZ" in zone_id:
            continue
        for engine in zone.get("SupportedEngines") or []:
            if engine.get("Engine") != _RDS_ENGINE:
                continue
            for version in engine.get("SupportedEngineVersions") or []:
                for category in version.get("SupportedCategorys") or []:
                    edition_id = _RDS_CATEGORY_TO_EDITION.get(
                        (category.get("Category") or "").lower()
                    )
                    storage_types = [
                        storage_type
                        for supported in category.get("SupportedStorageTypes") or []
                        if (storage_type := supported.get("StorageType"))
                        in _RDS_STORAGE_TYPES
                    ]
                    if not edition_id or not storage_types:
                        continue
                    offer = offers.setdefault(edition_id, {}).setdefault(
                        zone_id, {"versions": [], "storage_types": []}
                    )
                    if version["Version"] not in offer["versions"]:
                        offer["versions"].append(version["Version"])
                    for storage_type in storage_types:
                        if storage_type not in offer["storage_types"]:
                            offer["storage_types"].append(storage_type)
    return offers


def _fetch_rds_offers(client: RdsClient, region_id: str) -> dict:
    """Fetch the orderable PostgreSQL instance types of a region per edition.

    `DescribeAvailableZones` lists the editions, engine versions and storage
    types of the zones. `DescribeAvailableClasses` lists the orderable instance
    types of a zone for an edition, engine version and storage type (all
    required): it is called with the newest engine version of the edition in
    each zone and ESSD PL1, as older versions support fewer instance types, and
    the instance types do not differ by the cloud disk type.

    The engine versions of an instance type are looked up by calling it with
    the older versions as well, but only in the zone of the edition offering
    the most versions, to limit the heavily throttled calls (around 2 per 13
    seconds in a region, so e.g. 8 older versions of 3 editions take almost 3
    minutes).

    Returns:
        `{"complete": True, "zones": <see _parse_rds_available_zones>,
        "classes": {edition_id: {class_code: {"zones": [...], "versions": [...]}}}}`
        with the `{"zone_id", "engine_version", "storage_type"}` parameters an
        instance type was found with in each zone (to be used in price
        queries), and the engine versions it was found with.
    """
    # example DescribeAvailableZones response:
    # {
    #     'AvailableZones': [
    #         {
    #             'RegionId': 'eu-central-1',
    #             'ZoneId': 'eu-central-1a',
    #             'SupportedEngines': [
    #                 {
    #                     'Engine': 'PostgreSQL',
    #                     'SupportedEngineVersions': [
    #                         {
    #                             'Version': '17.0',
    #                             'SupportedCategorys': [
    #                                 {
    #                                     'Category': 'cluster',
    #                                     'SupportedStorageTypes': [
    #                                         {'StorageType': 'cloud_essd'},
    #                                         {'StorageType': 'cloud_auto'},
    #                                         {'StorageType': 'cloud_essd2'},
    #                                         {'StorageType': 'cloud_essd3'}
    #                                     ]
    #                                 },
    #                                 # ...
    #                             ]
    #                         },
    #                         # ...
    #                     ]
    #                 }
    #             ]
    #         },
    #         # ...
    #     ],
    #     'RequestId': '01A1E560-CDE4-3484-9C3A-5A99EBAC5936'
    # }
    zones = _parse_rds_available_zones(
        _rds_call(
            client.describe_available_zones_with_options,
            DescribeAvailableZonesRequest(region_id=region_id, engine=_RDS_ENGINE),
        ).get("AvailableZones")
        or []
    )
    classes: dict[str, dict] = {}

    def available_classes(edition_id: str, params: dict) -> list[str]:
        # example DescribeAvailableClasses response:
        # {
        #     'DBInstanceClasses': [
        #         {
        #             'DBInstanceClass': 'pg.n2.2c.2m',
        #             'DBInstanceStorageRange': {
        #                 'MaxValue': 64000,
        #                 'MinValue': 20,
        #                 'Step': 5
        #             }
        #         },
        #         # ...
        #     ],
        #     'RequestId': '01A1E561-0016-3460-8F6C-727574DB374B'
        # }
        available = _rds_call(
            client.describe_available_classes_with_options,
            DescribeAvailableClassesRequest(
                region_id=region_id,
                zone_id=params["zone_id"],
                engine=_RDS_ENGINE,
                engine_version=params["engine_version"],
                category=_RDS_EDITIONS[edition_id]["category"],
                dbinstance_storage_type=params["storage_type"],
                instance_charge_type="Postpaid",
                order_type="BUY",
                commodity_code=_RDS_COMMODITY_CODE,
            ),
        )
        found = [
            available_class["DBInstanceClass"]
            for available_class in available.get("DBInstanceClasses") or []
        ]
        for class_code in found:
            versions = (
                classes.setdefault(edition_id, {})
                .setdefault(class_code, {"zones": [], "versions": []})
                .get("versions")
            )
            if params["engine_version"] not in versions:
                versions.append(params["engine_version"])
        return found

    for edition_id, edition_zones in zones.items():
        newest = {}
        for zone_id, offer in edition_zones.items():
            newest[zone_id] = params = {
                "zone_id": zone_id,
                "engine_version": max(offer["versions"], key=float),
                "storage_type": (
                    "cloud_essd"
                    if "cloud_essd" in offer["storage_types"]
                    else offer["storage_types"][0]
                ),
            }
            for class_code in available_classes(edition_id, params):
                classes[edition_id][class_code]["zones"].append(params)
        # older engine versions, in the zone offering the most versions
        zone_id = max(edition_zones, key=lambda z: len(edition_zones[z]["versions"]))
        for version in edition_zones[zone_id]["versions"]:
            if version == newest[zone_id]["engine_version"]:
                continue
            params = {**newest[zone_id], "engine_version": version}
            for class_code in available_classes(edition_id, params):
                # only orderable with an older engine version
                if not classes[edition_id][class_code]["zones"]:
                    classes[edition_id][class_code]["zones"].append(params)
    return {"complete": True, "zones": zones, "classes": classes}


def _fetch_rds_class_specs(client: RdsClient, region_id: str) -> dict[str, dict]:
    """Fetch the specs and reference prices of the PostgreSQL instance types of a region.

    `ListClasses` returns (almost) the same instance types in all regions, also
    the ones not offered there, and legacy ones without an edition, so it needs
    to be filtered by `_fetch_rds_offers`. The `ReferencePrice` is the regional
    price of the instance type in USD cents per hour, but it is missing for
    some of the orderable instance types.
    """
    # example ListClasses response:
    # {
    #     'Items': [
    #         {
    #             'ClassCode': 'pg.n2e.2c.xc',
    #             'ClassGroup': '通用型',
    #             'Cpu': '2',
    #             'InstructionSetArch': 'arm',
    #             'MaxConnections': '400',
    #             'MaxIOMBPS': 'N/A',
    #             'MaxIOPS': 'N/A',
    #             'MemoryClass': ' 4GB（通用型）',
    #             'ReferencePrice': '6.9',
    #             'category': 'Cluster',
    #             'storageType': 'Cloud'
    #         },
    #         # ...
    #     ],
    #     'RegionId': 'eu-central-1',
    #     'RequestId': '01A1E560-CDE4-3484-9C3A-5A99EBAC5936'
    # }
    items = _rds_call(
        client.list_classes_with_options,
        ListClassesRequest(
            commodity_code=_RDS_COMMODITY_CODE,
            order_type="BUY",
            region_id=region_id,
            engine=_RDS_ENGINE,
        ),
    ).get("Items")
    return {item["ClassCode"]: item for item in items or []}


def _parse_rds_price(price: dict) -> dict:
    """Extract the unit prices of the priced modules from a `DescribePrice` response.

    Returns:
        `{"currency": "USD", "modules": {module code: unit price in USD}}`,
        e.g. `rds_class` (instance type, per hour) and `rds_storage` (a GB of
        storage, per hour), both for a single node in the Cluster Edition.
    """
    # example DescribePrice response (pg.n2.2c.1m with 100 GB ESSD PL1):
    # {
    #     'PriceInfo': {
    #         'Coupons': {'Coupon': []},
    #         'Currency': 'USD',
    #         'DiscountPrice': 0.0,
    #         'OrderLines': {
    #             '0': {
    #                 'moduleInstance': [
    #                     {
    #                         'moduleCode': 'rds_storage',
    #                         'priceType': 'hourPrice',
    #                         'pricingModule': True,
    #                         'originUnitFee': '0.06',
    #                         'standPrice': 6.0,
    #                         'moduleAttrs': [
    #                             {'code': 'rds_storage', 'unit': 'GB', 'value': '100'}
    #                         ],
    #                         # ...
    #                     },
    #                     {
    #                         'moduleCode': 'rds_class',
    #                         'priceType': 'hourPrice',
    #                         'pricingModule': True,
    #                         'originUnitFee': '8.27',
    #                         'standPrice': 8.27,
    #                         'moduleAttrs': [
    #                             {'code': 'rds_class', 'value': 'pg.n2.2c.1m'}
    #                         ],
    #                         # ...
    #                     },
    #                     # ...
    #                 ],
    #                 # ...
    #             }
    #         },
    #         'OriginalPrice': 0.1427,
    #         'RuleIds': {'RuleId': []},
    #         'TradePrice': 0.1427
    #     },
    #     'RequestId': '01A1E560-CDE4-3484-9C3A-5A99EBAC5936',
    #     'Rules': {'Rule': []},
    #     'ShowDiscount': True
    # }
    price_info = price.get("PriceInfo") or {}
    order_lines = price_info.get("OrderLines") or {}
    if isinstance(order_lines, dict):
        order_lines = order_lines.values()
    modules = {}
    for order_line in order_lines:
        for module in order_line.get("moduleInstance") or []:
            # unit price in USD cents, while `standPrice` is for all the units
            if module.get("pricingModule") and module.get("originUnitFee"):
                modules[module["moduleCode"]] = float(module["originUnitFee"]) / 100
    return {"currency": price_info.get("Currency"), "modules": modules}


def _fetch_rds_price(
    client: RdsClient,
    region_id: str,
    class_code: str,
    edition_id: str,
    zone_id: str,
    engine_version: str,
    storage_type: str,
    storage_size: int,
) -> Optional[dict]:
    """Fetch the pay-as-you-go price of a PostgreSQL instance using `DescribePrice`.

    Returns:
        The parsed prices (see `_parse_rds_price`), or `None` when the instance
        type is not sold in the region (e.g. listed as available, but without a
        pricing plan).
    """
    request = RdsDescribePriceRequest(
        region_id=region_id,
        zone_id=zone_id,
        engine=_RDS_ENGINE,
        engine_version=engine_version,
        dbinstance_class=class_code,
        dbinstance_storage=storage_size,
        dbinstance_storage_type=storage_type,
        pay_type="Postpaid",
        commodity_code=_RDS_COMMODITY_CODE,
        quantity=1,
        instance_used_type=0,
        order_type="BUY",
    )
    if edition_id == "cluster":
        # the nodes of a cluster need to be listed, each billed on its own
        request.dbnode = [
            DescribePriceRequestDBNode(class_code=class_code, zone_id=zone_id)
            for _ in range(_RDS_EDITIONS[edition_id]["billed_nodes"])
        ]
    try:
        return _parse_rds_price(_rds_call(client.describe_price_with_options, request))
    except Exception as e:
        # throttled or unreachable even after the retries: a missing price, not
        # a missing pricing plan
        level = WARN if any(x in str(e) for x in _RDS_TRANSIENT_ERRORS) else DEBUG
        logger.log(
            level, f"No RDS price for {class_code} in {region_id}/{zone_id}: {e}"
        )
        return None


# results of the slow, throttled RDS lookups shared by the database inventories
# of a run (bound to the session of the vendor), by the name of the lookup and
# the regions, kept for at most a few hours (when running without a session)
_rds_region_results: dict[tuple, tuple[object, float, dict[str, dict]]] = {}
_RDS_REGION_RESULTS_TTL = 6 * 60 * 60


def _rds_map_regions(vendor: Vendor, name: str, fetch, fallback) -> dict[str, dict]:
    """Run `fetch(client, region_id)` for all active regions in parallel threads.

    The results are kept for the rest of the run. Failing regions are logged,
    and get the `fallback` value.
    """
    clients = _rds_clients(vendor)
    key = (name, tuple(sorted(clients)))
    if key in _rds_region_results:
        session, fetched_at, results = _rds_region_results[key]
        if (
            session is vendor.session
            and monotonic() - fetched_at < _RDS_REGION_RESULTS_TTL
        ):
            return results
        del _rds_region_results[key]

    @cachier(hash_func=jsoned_hash, separate_files=True)
    def fetch_region(name: str, region_id: str):
        return fetch(clients[region_id], region_id)

    def fetch_region_or_fallback(region_id: str):
        try:
            return region_id, fetch_region(name, region_id), True
        except Exception as e:
            logger.error(f"Failed to fetch {name} in region {region_id}: {e}")
            return region_id, fallback, False

    vendor.progress_tracker.start_task(name=f"Fetching {name}", total=len(clients))
    results = {}
    complete = True
    # the flow control of the RDS endpoints is counted for each region
    with ThreadPoolExecutor(max_workers=max(len(clients), 1)) as executor:
        for region_id, result, succeeded in executor.map(
            fetch_region_or_fallback, clients
        ):
            results[region_id] = result
            complete = complete and succeeded
            vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    if complete:
        _rds_region_results[key] = (vendor.session, monotonic(), results)
    return results


def _get_rds_offers(vendor: Vendor) -> dict[str, dict]:
    """Orderable PostgreSQL instance types of the active regions, see `_fetch_rds_offers`.

    Regions failing to be looked up are returned without zones and instance
    types, marked with `"complete": False`.
    """
    return _rds_map_regions(
        vendor,
        "database availability",
        _fetch_rds_offers,
        {"complete": False, "zones": {}, "classes": {}},
    )


def _get_rds_class_specs(vendor: Vendor) -> dict[str, dict]:
    """Specs of the PostgreSQL instance types of the active regions, see `_fetch_rds_class_specs`."""
    return _rds_map_regions(
        vendor, "database instance types", _fetch_rds_class_specs, {}
    )


def _rds_class_memory(spec: dict) -> Optional[int]:
    """Memory (MiB) of an RDS instance type from the `MemoryClass` of `ListClasses`.

    E.g. " 4GB（通用型）", "16G (Intel SGX 安全增强)" or " 32GB（即将停售）".
    """
    match = search(r"(\d+(?:\.\d+)?)\s*G", spec.get("MemoryClass") or "")
    return int(float(match.group(1)) * 1024) if match else None


def _rds_class_status(
    spec: dict, orderable: bool, complete: bool = True
) -> Optional[Status]:
    """Lifecycle of an RDS instance type.

    Orderable in at least one region -> ACTIVE, or PLANNED_FOR_RETIREMENT when
    `ListClasses` notes its end of sale. Not orderable anywhere -> RETIRED when
    the end of sale is noted, otherwise unknown (`None`): not to be listed.

    When the lookup of the orderable instance types was not `complete` (failed
    in some regions), an instance type not found is not known to be gone, so it
    is handled as an orderable one.
    """
    memory_class = spec.get("MemoryClass") or ""
    end_of_sale = _RDS_END_OF_SALE in memory_class
    end_of_sale_soon = _RDS_END_OF_SALE_SOON in memory_class
    if orderable or not complete:
        if end_of_sale or end_of_sale_soon:
            return Status.PLANNED_FOR_RETIREMENT
        return Status.ACTIVE
    if end_of_sale or end_of_sale_soon:
        return Status.RETIRED
    return None


def _rds_security_features(family: Optional[str]) -> list[DatabaseSecurityFeature]:
    """Security features of an RDS for PostgreSQL instance family.

    IP address whitelists, VPC placement, AD domain authentication, SSL
    encryption (the instance accepts only SSL connections with an ACL
    configured, and client CA certificates can be required) and SQL audit with
    cloud disks in all editions. Cloud disk encryption supports customer
    managed KMS keys only on the dedicated instance types, the general-purpose
    ones are limited to the service key.

    - https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/features-of-apsaradb-rds-for-postgresql
    - https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/configure-ssl-encryption-for-an-apsaradb-rds-for-postgresql-instance
    - https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/connect-to-an-apsaradb-rds-for-postgresql-instance-over-ssl-connections
    - https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/configure-disk-encryption-for-an-apsaradb-rds-for-postgresql-instance
    """
    features = [
        DatabaseSecurityFeature.IP_FILTERING,
        DatabaseSecurityFeature.PRIVATE_NETWORK,
        DatabaseSecurityFeature.IDENTITY_BASED_AUTH,
        DatabaseSecurityFeature.CLIENT_CERT_AUTH,
        DatabaseSecurityFeature.ENFORCED_TLS,
    ]
    if family != "General Purpose":
        features.append(DatabaseSecurityFeature.CUSTOMER_MANAGED_KEYS)
    features.append(DatabaseSecurityFeature.AUDIT_LOGGING)
    return features


def _rds_class_editions(specs: dict[str, dict]) -> dict[str, tuple[str, dict]]:
    """Edition and specs of the instance types listed in any region.

    Returns:
        `{class_code: (edition_id, specs in the first region listing it)}`,
        without the legacy instance types not belonging to an edition.
    """
    classes = {}
    for region_specs in specs.values():
        for class_code, spec in region_specs.items():
            edition_id = _RDS_CATEGORY_TO_EDITION.get(
                (spec.get("category") or "").lower()
            )
            if edition_id:
                classes.setdefault(class_code, (edition_id, spec))
    return classes


def _database_edition_id(database) -> Optional[str]:
    """Edition of an already inventoried database."""
    category = (database.api_reference_object or {}).get("category") or ""
    return _RDS_CATEGORY_TO_EDITION.get(category.lower())


def inventory_databases(vendor):
    """List all ApsaraDB RDS for PostgreSQL instance types.

    An instance type is listed for the edition it belongs to (Basic,
    High-availability or Cluster Edition), when it is orderable with
    pay-as-you-go billing in at least one zone, or at its end of sale.

    Data sources:

    - <https://www.alibabacloud.com/help/en/rds/developer-reference/api-rds-2014-08-15-listclasses>
    - <https://www.alibabacloud.com/help/en/rds/developer-reference/api-rds-2014-08-15-describeavailablezones>
    - <https://www.alibabacloud.com/help/en/rds/developer-reference/api-rds-2014-08-15-describeavailableclasses>
    - <https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/primary-apsaradb-rds-for-postgresql-instance-types>

    Lifecycle: ACTIVE when orderable, PLANNED_FOR_RETIREMENT when orderable
    with an end of sale note in `ListClasses`, RETIRED when not orderable
    anymore with that note. Instance types are not retired or dropped when the
    orderable ones could not be looked up in all regions.
    """
    offers = _get_rds_offers(vendor)
    specs = _get_rds_class_specs(vendor)
    complete = all(offer.get("complete", True) for offer in offers.values())
    if not complete:
        vendor.log(
            "Database availability is not known in all regions, "
            "keeping the instance types not found as orderable.",
            level=WARN,
        )

    orderable = {
        (edition_id, class_code)
        for offer in offers.values()
        for edition_id, classes in offer["classes"].items()
        for class_code in classes
    }
    # engine versions an instance type is orderable with in any region
    versions: dict[tuple[str, str], set] = defaultdict(set)
    for offer in offers.values():
        for edition_id, edition_classes in offer["classes"].items():
            for class_code, available in edition_classes.items():
                versions[(edition_id, class_code)].update(available["versions"])
    # disk types offered for an edition in any zone
    storage_types: dict[str, set] = defaultdict(set)
    for offer in offers.values():
        for edition_id, zones in offer["zones"].items():
            for zone_offer in zones.values():
                storage_types[edition_id].update(zone_offer["storage_types"])

    classes = _rds_class_editions(specs)
    unknown = sorted(
        class_code for _, class_code in orderable if class_code not in classes
    )
    if unknown:
        vendor.log(
            f"No specs for {len(unknown)} orderable database instance types "
            f"(e.g. {', '.join(unknown[:5])}), skipping.",
            level=WARN,
        )

    items = []
    for class_code, (edition_id, spec) in sorted(classes.items()):
        with sentry_capture_or_raise(vendor=vendor):
            status = _rds_class_status(
                spec, (edition_id, class_code) in orderable, complete
            )
            if status is None:
                continue
            edition = _RDS_EDITIONS[edition_id]
            class_group = spec.get("ClassGroup") or ""
            family = _RDS_CLASS_GROUP_TO_FAMILY.get(class_group)
            if family is None:
                vendor.log(
                    f"Unknown database instance family: {class_group}", level=WARN
                )
                family = class_group or None
            vcpus = int(spec["Cpu"].strip())
            memory_amount = _rds_class_memory(spec)
            arm = (spec.get("InstructionSetArch") or "").lower() == "arm"
            description_parts = [
                f"{vcpus} vCPUs",
                f"{memory_amount / 1024:g} GiB RAM" if memory_amount else None,
                "ARM" if arm else None,
            ]
            compatible_storage_types = [
                storage_type
                for storage_type in _RDS_STORAGE_TYPES
                if storage_type in storage_types[edition_id]
            ]
            sizes = [
                (
                    _RDS_STORAGE_TYPES[storage_type]["min_size"],
                    _RDS_STORAGE_TYPES[storage_type]["max_size"],
                )
                for storage_type in compatible_storage_types
            ]
            ha_strategy = [edition["ha_strategy"]]
            # https://www.alibabacloud.com/help/doc-detail/42437.htm
            # 99.99% for the High-availability Edition on dedicated, and 99.95% on
            # general-purpose instance types. No SLA for the Basic Edition, and
            # the Cluster Edition for PostgreSQL is not covered there.
            if edition_id == "ha":
                sla = 99.95 if family == "General Purpose" else 99.99
            else:
                sla = None
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "database_id": class_code,
                    "name": class_code,
                    "api_reference": class_code,
                    # https://www.pulumi.com/registry/packages/alicloud/api-docs/rds/instance/
                    "api_reference_object": {
                        "engine": _RDS_ENGINE,
                        "instance_type": class_code,
                        "category": edition["category"],
                    },
                    "display_name": class_code,
                    "description": (
                        f"{family} {edition['name']} "
                        f"({', '.join(filter(None, description_parts))})"
                    ),
                    "family": family,
                    # e.g. pg.x4 of pg.x4.large.2c
                    "series": ".".join(class_code.split(".")[:2]),
                    # the underlying ECS instance type is not disclosed
                    "server_id": None,
                    "vcpus": vcpus,
                    "memory_amount": memory_amount,
                    "engine": DatabaseEngine.POSTGRESQL,
                    "wire_protocol": DatabaseWireProtocol.POSTGRESQL,
                    "engine_versions": [
                        f"{float(version):g}"
                        for version in sorted(
                            versions[(edition_id, class_code)], key=float
                        )
                    ],
                    # https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/update-the-minor-engine-version-of-an-apsaradb-rds-for-postgresql-instance
                    # Automatic minor engine version updates in the maintenance window.
                    "auto_upgrade_versions": True,
                    "ha": edition["ha"],
                    "ha_strategy": ha_strategy,
                    "max_read_replicas": edition["max_read_replicas"],
                    # Instance parameters can be modified in all editions.
                    "custom_config": True,
                    # Supported PostgreSQL extensions can be installed.
                    "custom_extensions": True,
                    "storage_size": 0,
                    # API and documentation sizes are GiB
                    "storage_extra_min": (
                        round(min(size[0] for size in sizes) * _GIB_TO_GB)
                        if sizes
                        else None
                    ),
                    "storage_extra_max": (
                        round(max(size[1] for size in sizes) * _GIB_TO_GB)
                        if sizes
                        else None
                    ),
                    # Automatic storage expansion of cloud disks in all editions.
                    "storage_extra_autosize": True,
                    "compatible_storage_ids": [
                        _rds_storage_id(storage_type, edition_id)
                        for storage_type in compatible_storage_types
                    ],
                    # Cloud disk encryption in all editions with ESSDs.
                    "disk_encryption": True,
                    # https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/back-up-an-apsaradb-rds-for-postgresql-instance
                    # https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/restore-data-of-an-apsaradb-rds-for-postgresql-instance
                    # Automatic data backups, and point-in-time restore within the
                    # log backup retention, which is up to the data backup retention
                    # of 730 days. Log backups are not supported in the Basic Edition.
                    "scheduled_backups": True,
                    "continuous_backups": edition["continuous_backups"],
                    # https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/use-pgbouncer-to-enable-or-disable-connection-pooling
                    "connection_pool": True,
                    # Enhanced Monitoring of the host and the engine, and the
                    # Database Autonomy Service (DAS) in all editions.
                    "system_monitoring": True,
                    "database_monitoring": True,
                    "sla": sla,
                    "security_features": _rds_security_features(family),
                    "status": status,
                }
            )
    return items


def _rds_region_prices(
    client: RdsClient,
    region_id: str,
    offer: dict,
    specs: dict[str, dict],
    class_codes: Collection[str],
) -> dict[str, tuple[float, str]]:
    """Hourly price (in USD) and currency of the orderable `class_codes` of a region.

    The `ReferencePrice` of `ListClasses` is used when available, and
    `DescribePrice` is called for the rest of the orderable instance types.
    Prices are per node in the Cluster Edition.
    """
    prices = {}
    for edition_id, classes in offer["classes"].items():
        for class_code, available in classes.items():
            if class_code not in class_codes:
                continue
            params = available["zones"][0]
            reference_price = specs.get(class_code, {}).get("ReferencePrice")
            if reference_price:
                # USD cents
                prices[class_code] = (float(reference_price) / 100, "USD")
                continue
            price = _fetch_rds_price(
                client=client,
                region_id=region_id,
                class_code=class_code,
                edition_id=edition_id,
                storage_size=_RDS_STORAGE_TYPES[params["storage_type"]]["min_size"],
                **params,
            )
            if price and price["modules"].get("rds_class"):
                prices[class_code] = (price["modules"]["rds_class"], price["currency"])
    return prices


def inventory_database_prices(vendor):
    """List the pay-as-you-go ApsaraDB RDS for PostgreSQL instance prices in all regions.

    The price of an instance type is listed in the regions with at least one
    zone where it is orderable, for the deployments of its edition: the
    High-availability Edition price covers both nodes, in a single or in
    multiple zones for the same price; the Cluster Edition is billed per node,
    and stored for the smallest cluster of 2 nodes.

    Data sources:

    - <https://www.alibabacloud.com/help/en/rds/developer-reference/api-rds-2014-08-15-listclasses>
    - <https://www.alibabacloud.com/help/en/rds/developer-reference/api-rds-2014-08-15-describeprice>
    """
    offers = _get_rds_offers(vendor)
    specs = _get_rds_class_specs(vendor)
    clients = _rds_clients(vendor)
    editions = {
        database.database_id: _database_edition_id(database)
        for database in vendor.databases
        if database.status.is_orderable
    }

    vendor.progress_tracker.start_task(
        name="Fetching database price(s)", total=len(offers)
    )

    def fetch_region_prices(region_id: str):
        try:
            return region_id, _rds_region_prices(
                clients[region_id],
                region_id,
                offers[region_id],
                specs.get(region_id, {}),
                editions.keys(),
            )
        except Exception as e:
            logger.error(f"Failed to get database prices in region {region_id}: {e}")
            return region_id, {}

    items = []
    with ThreadPoolExecutor(max_workers=max(len(offers), 1)) as executor:
        for region_id, prices in executor.map(fetch_region_prices, offers):
            offer = offers[region_id]
            for class_code, (price, currency) in sorted(prices.items()):
                edition_id = editions.get(class_code)
                if not edition_id or class_code not in offer["classes"].get(
                    edition_id, {}
                ):
                    continue
                edition = _RDS_EDITIONS[edition_id]
                multi_zone = len(offer["zones"].get(edition_id, {})) > 1
                for ha in edition["ha"]:
                    if ha == DatabaseHaLevel.MULTI_ZONE and not multi_zone:
                        continue
                    items.append(
                        {
                            "vendor_id": vendor.vendor_id,
                            "region_id": region_id,
                            "database_id": class_code,
                            "allocation": Allocation.ONDEMAND,
                            "ha": ha,
                            "ha_strategy": edition["ha_strategy"],
                            "unit": PriceUnit.HOUR,
                            "price": round(price * edition["billed_nodes"], 6),
                            "price_upfront": 0,
                            "price_tiered": [],
                            "currency": currency,
                        }
                    )
            vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return items


def inventory_database_storages(vendor):
    """List the cloud disk types of ApsaraDB RDS for PostgreSQL per edition.

    The price of a disk type depends on the edition of the instance, so each
    disk type is listed once for each edition, see `_rds_storage_id`.

    Data sources:

    - <https://www.alibabacloud.com/help/en/rds/apsaradb-rds-for-postgresql/primary-apsaradb-rds-for-postgresql-instance-types>
    - <https://www.alibabacloud.com/help/en/ecs/user-guide/essds>

    Sizes are specified in GiB in the Alibaba Cloud documentation and are
    converted to GB here. Throughput values are in MB/s.
    """
    items = []
    for edition_id, edition in _RDS_EDITIONS.items():
        nodes = (
            f" Priced for {edition['billed_nodes']} nodes, each with its own disk."
            if edition["billed_nodes"] > 1
            else ""
        )
        for storage_type, disk in _RDS_STORAGE_TYPES.items():
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "database_storage_id": _rds_storage_id(storage_type, edition_id),
                    "name": f"{disk['name']} ({edition['name']})",
                    "description": (
                        f"{disk['description']} for RDS {edition['name']}.{nodes}"
                    ),
                    "scope": DatabaseStorageScope.DATA,
                    "min_size": round(disk["min_size"] * _GIB_TO_GB),
                    "max_size": round(disk["max_size"] * _GIB_TO_GB),
                    "max_iops": disk["max_iops"],
                    "max_throughput": disk["max_throughput"],
                }
            )
    return items


def _rds_region_storage_prices(
    client: RdsClient, region_id: str, offer: dict, specs: dict[str, dict]
) -> dict[str, tuple[float, str]]:
    """Hourly price (in USD) of a GB and currency of the database storages of a region.

    The storage price is only available as part of the price of an instance, so
    `DescribePrice` is called with an orderable instance type of each edition
    for each of its disk types. Prices are per node in the Cluster Edition.
    """
    prices = {}
    for edition_id, zones in offer["zones"].items():
        storage_types = {
            storage_type
            for zone_offer in zones.values()
            for storage_type in zone_offer["storage_types"]
        }
        # try the instance types known to be sold (with a reference price) first
        classes = sorted(
            offer["classes"].get(edition_id, {}).items(),
            key=lambda item: (
                not specs.get(item[0], {}).get("ReferencePrice"),
                item[0],
            ),
        )
        for storage_type in sorted(storage_types):
            size = _RDS_STORAGE_TYPES[storage_type]["min_size"]
            # any zone of an instance type offering the disk type
            candidates = [
                (class_code, params)
                for class_code, available in classes
                if (
                    params := next(
                        (
                            zone_params
                            for zone_params in available["zones"]
                            if storage_type
                            in zones[zone_params["zone_id"]]["storage_types"]
                        ),
                        None,
                    )
                )
            ]
            for class_code, params in candidates[:3]:
                price = _fetch_rds_price(
                    client=client,
                    region_id=region_id,
                    class_code=class_code,
                    edition_id=edition_id,
                    zone_id=params["zone_id"],
                    engine_version=params["engine_version"],
                    storage_type=storage_type,
                    storage_size=size,
                )
                if price and price["modules"].get("rds_storage"):
                    prices[_rds_storage_id(storage_type, edition_id)] = (
                        price["modules"]["rds_storage"],
                        price["currency"],
                    )
                    break
    return prices


def inventory_database_storage_prices(vendor):
    """List the ApsaraDB RDS for PostgreSQL storage prices in all regions.

    Stored for the nodes covered by the instance price of the edition, see
    `inventory_database_prices`: both nodes of the High-availability Edition
    (as billed), and 2 nodes of the Cluster Edition (billed per node).

    Data source: <https://www.alibabacloud.com/help/en/rds/developer-reference/api-rds-2014-08-15-describeprice>
    """
    offers = _get_rds_offers(vendor)
    specs = _get_rds_class_specs(vendor)
    clients = _rds_clients(vendor)
    storage_ids = {storage.database_storage_id for storage in vendor.database_storages}

    vendor.progress_tracker.start_task(
        name="Fetching database storage price(s)", total=len(offers)
    )

    def fetch_region_prices(region_id: str):
        try:
            return region_id, _rds_region_storage_prices(
                clients[region_id],
                region_id,
                offers[region_id],
                specs.get(region_id, {}),
            )
        except Exception as e:
            logger.error(
                f"Failed to get database storage prices in region {region_id}: {e}"
            )
            return region_id, {}

    items = []
    with ThreadPoolExecutor(max_workers=max(len(offers), 1)) as executor:
        for region_id, prices in executor.map(fetch_region_prices, offers):
            for storage_id, (price, currency) in sorted(prices.items()):
                if storage_id not in storage_ids:
                    continue
                edition_id = storage_id.rsplit("-", 1)[-1]
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": region_id,
                        "database_storage_id": storage_id,
                        "unit": PriceUnit.GB_MONTH,
                        "price": round(
                            price
                            * _RDS_EDITIONS[edition_id]["billed_nodes"]
                            * _HOURS_PER_MONTH,
                            6,
                        ),
                        "price_upfront": 0,
                        "price_tiered": [],
                        "currency": currency,
                    }
                )
            vendor.progress_tracker.advance_task()
    vendor.progress_tracker.hide_task()
    return items
