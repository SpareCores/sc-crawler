import random
import re
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from itertools import chain
from logging import INFO, WARN
from os import environ
from time import sleep, time
from typing import Optional

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
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    DatabaseEngine,
    DatabaseStorageScope,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)
from ..tables import ServerPrice, Vendor
from ..utils import _GIB_TO_GB, _HOURS_PER_MONTH, jsoned_hash
from ..vendor_helpers import get_region_by_id, merge_database_catalog_rows

try:
    from alibabacloud_rds20140815 import models as rds_models
except ImportError:  # pragma: no cover
    rds_models = None

_CACHIER_WATCH_ERROR = "Cannot add watch"
_cachier_call_lock = threading.Lock()


def _cached_call(fn, /, *args, **kwargs):
    """Call a @cachier function without duplicate FSEvents watches."""
    with _cachier_call_lock:
        try:
            return fn(*args, **kwargs)
        except RuntimeError as exc:
            if _CACHIER_WATCH_ERROR not in str(exc):
                raise
            return fn(*args, cachier__skip_cache=True, **kwargs)


_RDS_ENGINE = "PostgreSQL"
_RDS_COMMODITY = "bards_intl"
_RDS_ORDER_TYPE = "BUY"
_RDS_PAY_TYPE = "Postpaid"
_RDS_DEFAULT_STORAGE_GIB = 20
_RDS_DEFAULT_CATEGORIES = frozenset({"Basic", "HighAvailability", "cluster"})
_RDS_DEFAULT_STORAGE_TYPES = (
    "cloud_essd",
    "cloud_auto",
    "cloud_essd2",
    "cloud_essd3",
)
_RDS_MEMORY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*G(?:i?B)?", re.IGNORECASE)

# ##############################################################################
# Internal helpers

_ALICLOUD_MAX_ATTEMPTS = 8
_ALICLOUD_RETRY_BASE_SLEEP_S = 1.0
_ALICLOUD_REQUEST_SLEEP_S = 0.75


def _alicloud_is_not_found(exc: Exception) -> bool:
    message = str(exc)
    return "InvalidCondition.NotFound" in message or "No class found" in message


def _alicloud_is_retryable(exc: Exception) -> bool:
    message = str(exc)
    return (
        "Throttling" in message
        or "flow control" in message
        or "SDK.HttpError" in message
        or "Failed to establish a new connection" in message
        or "Name or service not known" in message
        or "Max retries exceeded" in message
    )


def _alicloud_error_label(exc: Exception) -> str:
    message = str(exc)
    for label in (
        "Throttling.User",
        "Throttling",
        "MissingParameter",
        "InvalidCondition.NotFound",
    ):
        if label in message:
            return label
    first_line = message.split("\n", 1)[0]
    if first_line.startswith("Error: "):
        first_line = first_line[7:]
    return first_line[:60]


def _alicloud_api_call(call, *, ignore_not_found: bool = False):
    """Call Alicloud APIs with basic retry/backoff for throttling."""
    for attempt in range(1, _ALICLOUD_MAX_ATTEMPTS + 1):
        try:
            result = call()
            if _ALICLOUD_REQUEST_SLEEP_S:
                sleep(_ALICLOUD_REQUEST_SLEEP_S)
            return result
        except Exception as exc:
            if _alicloud_is_not_found(exc):
                if ignore_not_found:
                    return None
                raise
            if attempt >= _ALICLOUD_MAX_ATTEMPTS or not _alicloud_is_retryable(exc):
                raise
            sleep_s = min(
                20.0, _ALICLOUD_RETRY_BASE_SLEEP_S * (2 ** (attempt - 1))
            )
            sleep_s *= 0.8 + 0.4 * random.random()
            logger.warning(
                "Alicloud API retry %d/%d: %s (sleep %.2fs)",
                attempt,
                _ALICLOUD_MAX_ATTEMPTS,
                _alicloud_error_label(exc),
                sleep_s,
            )
            sleep(sleep_s)
    raise RuntimeError("unreachable")


def _alibabacloud_config(region_id: str) -> Config:
    """Build SDK config with direct credentials, avoiding DefaultCredentialsProvider with unnecessary background scheduler."""
    access_key_id = environ.get("ALIBABA_CLOUD_ACCESS_KEY_ID")
    access_key_secret = environ.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    if access_key_id and access_key_secret:
        config = Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            region_id=region_id,
        )
        security_token = environ.get("ALIBABA_CLOUD_SECURITY_TOKEN")
        if security_token:
            config.security_token = security_token
        return config
    return Config(credential=CredClient(), region_id=region_id)


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


@cachier(hash_func=jsoned_hash, separate_files=True)
def _cached_fetch_region_availability(
    region_id: str,
    instance_charge_type: str,
    destination_resource: str,
    resource_type: str,
    extra_request_params: dict,
) -> list[dict]:
    request = DescribeAvailableResourceRequest(
        region_id=region_id,
        instance_charge_type=instance_charge_type,
        destination_resource=destination_resource,
        resource_type=resource_type,
        **extra_request_params,
    )
    runtime = RuntimeOptions()
    response = _alicloud_api_call(
        lambda: _ecs_client(region_id).describe_available_resource_with_options(
            request, runtime
        )
    )
    available_zones = response.body.available_zones
    if not available_zones or not available_zones.available_zone:
        return []
    return [
        resource.to_map()
        for resource in response.body.available_zones.available_zone
    ]


@cachier(hash_func=jsoned_hash, separate_files=True)
def _cached_fetch_zones_for_region(region_id: str) -> list[dict]:
    request = DescribeZonesRequest(region_id=region_id, accept_language="en-US")
    response = _alicloud_api_call(
        lambda: _ecs_client(region_id).describe_zones(request)
    )
    return [
        {
            "zone_id": zone.get("ZoneId"),
            "name": zone.get("LocalName"),
            "api_reference": zone.get("ZoneId"),
            "display_name": zone.get("LocalName"),
        }
        for zone in response.body.to_map()["Zones"]["Zone"]
    ]


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
    response = _alicloud_api_call(
        lambda: client.query_sku_price_list_with_options(request, runtime)
    )
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
        response = _alicloud_api_call(
            lambda: client.query_sku_price_list_with_options(request, runtime)
        )
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

    def fetch_region_availability(region_id: str) -> tuple[str, list[dict]]:
        resources = []

        def on_error():
            vendor.log(
                f"Failed to get availability info for region {region_id}",
                WARN,
            )

        with sentry_capture_or_raise(vendor=vendor, on_error=on_error):
            resources = _cached_call(
                _cached_fetch_region_availability,
                region_id,
                instance_charge_type,
                destination_resource,
                resource_type,
                extra_request_params,
            )
        return region_id, resources

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


def _is_resource_available(
    region_availability_info: dict[str, list[dict]],
    region_id: str,
    zone_id: str,
    server_id: str,
    resource_type: str = "InstanceType",
    status_category: str = "WithStock",
) -> bool:
    """Check if a specific resource is available in a specific region and zone.

    Args:
        region_availability_info: The region availability information.
        region_id: The region ID.
        zone_id: The zone ID.
        server_id: The server ID.
        resource_type: The resource type, defaults to "InstanceType".
        status_category: The status category to check for, defaults to "WithStock".
    """
    if not region_availability_info:
        return False

    zone_availability_info = next(
        (
            r
            for r in region_availability_info.get(region_id, [])
            if r.get("ZoneId") == zone_id
        ),
        None,
    )

    if not zone_availability_info:
        return False

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
        {},
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

    if server_info.get("StatusCategory") == status_category:
        return True

    return False


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
        resources = []

        def on_error():
            vendor.log(f"Failed to get spot info for region {region_id}", WARN)

        with sentry_capture_or_raise(vendor=vendor, on_error=on_error):
            request = DescribeSpotAdviceRequest(
                region_id=region_id,
                **extra_request_params,
            )
            runtime = RuntimeOptions()
            response = _alicloud_api_call(
                lambda: client.describe_spot_advice_with_options(request, runtime)
            )
            if response.body:
                spot_zones = response.body.available_spot_zones
                if spot_zones and spot_zones.available_spot_zone:
                    resources = [
                        spot_zone.to_map()
                        for spot_zone in spot_zones.available_spot_zone
                    ]
        vendor.progress_tracker.advance_task()
        return region_id, resources

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
            response = _alicloud_api_call(
                lambda: client.describe_price_with_options(request, runtime)
            )
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
    response = _alicloud_api_call(lambda: _ecs_client().describe_regions(request))
    regions = [region.to_map() for region in response.body.regions.region]

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

    def fetch_zones_for_region(region_id):
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
            for zone in _cached_call(_cached_fetch_zones_for_region, region_id):
                zone_items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": region_id,
                        **zone,
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
    """List all server types at Alibaba Cloud using the `DescribeInstanceTypes` API endpoint."""
    client = _ecs_client()
    additional_attributes = ["NetworkInfo.BandwidthWeighting"]
    request = DescribeInstanceTypesRequest(
        max_results=1000, additional_attributes=additional_attributes
    )
    instance_types = []

    def on_error():
        vendor.log("Failed to fetch Alibaba Cloud instance types", WARN)

    with sentry_capture_or_raise(vendor=vendor, on_error=on_error):
        response = _alicloud_api_call(
            lambda: client.describe_instance_types(request)
        )
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
            response = _alicloud_api_call(
                lambda: client.describe_instance_types(request)
            )
            for instance_type in response.body.instance_types.instance_type:
                instance_types.append(instance_type.to_map())

    region_availability_info: dict[str, list[dict]] = _get_region_availability_info(
        vendor
    )

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
        family = instance_type.get("InstanceTypeFamily")
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
        gpu_memory_per_gpu = instance_type.get("GPUMemorySize", 0) * 1024  # GiB -> MiB
        # GPUMemorySize contains total memory for fractional or single GPUs, but per-GPU memory for multiple GPUs
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
        server_id = instance_type.get("InstanceTypeId")
        status = (
            Status.ACTIVE
            if any(
                _is_resource_available(
                    region_availability_info,
                    region_id,
                    zone_info.get("ZoneId"),
                    server_id,
                )
                for region_id, zones in region_availability_info.items()
                for zone_info in zones
            )
            else Status.INACTIVE
        )

        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "server_id": server_id,
                "name": server_id,
                "api_reference": server_id,
                "display_name": server_id,
                "description": description,
                "family": family,
                "vcpus": vcpus,
                "hypervisor": "KVM",
                "cpu_allocation": _determine_cpu_allocation_type(instance_type),
                "cpu_cores": instance_type.get("CpuCoreCount", 0),
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
                "gpu_count": gpu_count,
                "gpu_memory_min": gpu_memory_per_gpu,
                "gpu_memory_total": gpu_memory_total,
                # TODO fill in from GPUSpec? or just let the inspector fill it in?
                "gpu_manufacturer": gpu_manufacturer,
                "gpu_family": gpu_family,
                "gpu_model": gpu_model,
                "gpus": [],
                "storage_size": storage_size,
                "storage_type": storage_type,
                "storages": [],
                # TODO: have to implement manual mapping here too, no detailed
                # network info available for every instance type in API response
                **_parse_network_fields(instance_type),
                "inbound_traffic": 0,
                "outbound_traffic": 0,
                "ipv4": 0,
                "status": status,
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
            status = (
                Status.ACTIVE
                if _is_resource_available(
                    region_availability_info, region.region_id, zone.zone_id, server_id
                )
                else Status.INACTIVE
            )

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
            f"{counts[Status.INACTIVE]} INACTIVE server prices",
            level=INFO,
        )
    vendor.log(
        f"OVERALL: Found {overall[Status.ACTIVE]} ACTIVE and "
        f"{overall[Status.INACTIVE]} INACTIVE server prices",
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
        random.shuffle(ondemand_instances[region_id])

    def fetch_spot_instance_price(
        region_id: str, zone_instance_list: list[tuple[str, str]], client: EcsClient
    ):
        spot_instances = []
        start_time = time()

        for zone_id, instance_type in zone_instance_list:
            if time() - start_time >= sample_time:
                break

            def on_error(
                instance_type=instance_type,
                zone_id=zone_id,
                region_id=region_id,
            ):
                vendor.log(
                    f"Failed to get spot price for {instance_type} "
                    f"in {region_id}/{zone_id}",
                    WARN,
                )

            with sentry_capture_or_raise(vendor=vendor, on_error=on_error):
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


def _rds_client(region_id: str):
    from alibabacloud_rds20140815.client import Client as RdsClient

    return RdsClient(_alibabacloud_config(region_id))


def _rds_clients(vendor: Vendor) -> dict:
    """Create RDS clients for all regions (call from the main thread before workers)."""
    return {
        region.region_id: _rds_client(region.region_id) for region in vendor.regions
    }


def _rds_runtime() -> RuntimeOptions:
    return RuntimeOptions(read_timeout=60000, connect_timeout=60000)


@dataclass(frozen=True, slots=True)
class _RdsPriceCombo:
    zone_id: str
    engine_version: str
    category: str
    storage_types: tuple[str, ...]


def _optional_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_rds_vcpu(value) -> int | None:
    parsed = _optional_float(value)
    return int(parsed) if parsed is not None else None


def _parse_rds_memory_amount(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(float(value) * 1024)
    match = _RDS_MEMORY_RE.search(str(value))
    if not match:
        return None
    return int(float(match.group(1)) * 1024)


def _dig_list(payload, *keys):
    current = payload
    for key in keys:
        if current is None:
            return []
        if isinstance(current, dict):
            current = current.get(key)
        else:
            value = getattr(current, key, None)
            current = value.to_map() if hasattr(value, "to_map") else value
    if current is None:
        return []
    if isinstance(current, list):
        return current
    if isinstance(current, dict):
        for nested in current.values():
            if isinstance(nested, list):
                return nested
    return [current]


def _postgres_zones(zones_payload: dict) -> list[dict]:
    return _dig_list(zones_payload, "AvailableZones", "AvailableZone") or _dig_list(
        zones_payload, "AvailableZones"
    )


def _postgres_category_storage_types(category_entry: dict) -> list[str]:
    storage_types: list[str] = []
    for storage in _dig_list(
        category_entry, "SupportedStorageTypes", "SupportedStorageType"
    ) or _dig_list(category_entry, "SupportedStorageTypes"):
        if isinstance(storage, dict):
            storage_type = storage.get("StorageType")
            if storage_type:
                storage_types.append(storage_type)
    return storage_types or list(_RDS_DEFAULT_STORAGE_TYPES)


def _postgres_price_combos(zones_payload: dict) -> list[_RdsPriceCombo]:
    combos: list[_RdsPriceCombo] = []
    for zone in _postgres_zones(zones_payload):
        zone_id = zone.get("ZoneId")
        if not zone_id:
            continue
        for engine in _dig_list(
            zone, "SupportedEngines", "SupportedEngine"
        ) or _dig_list(zone, "SupportedEngines"):
            engine_name = engine.get("Engine") or engine.get("engine")
            if engine_name and engine_name.lower() != _RDS_ENGINE.lower():
                continue
            for version_entry in _dig_list(
                engine, "SupportedEngineVersions", "SupportedEngineVersion"
            ) or _dig_list(engine, "SupportedEngineVersions"):
                engine_version = version_entry.get("Version") or version_entry.get(
                    "version"
                )
                if not engine_version:
                    continue
                for category_entry in _dig_list(
                    version_entry, "SupportedCategorys", "SupportedCategory"
                ) or _dig_list(version_entry, "SupportedCategorys"):
                    category = category_entry.get("Category")
                    if not category or category not in _RDS_DEFAULT_CATEGORIES:
                        continue
                    combos.append(
                        _RdsPriceCombo(
                            zone_id=zone_id,
                            engine_version=str(engine_version),
                            category=category,
                            storage_types=tuple(
                                _postgres_category_storage_types(category_entry)
                            ),
                        )
                    )
    return combos


def _pick_postgres_price_combo(
    combos: list[_RdsPriceCombo],
) -> _RdsPriceCombo | None:
    if not combos:
        return None

    def _sort_key(combo: _RdsPriceCombo) -> tuple:
        version_parts = [
            int(part) for part in combo.engine_version.split(".") if part.isdigit()
        ]
        maz_penalty = 1 if "MAZ" in combo.zone_id else 0
        category_order = {"Basic": 0, "HighAvailability": 1, "cluster": 2}.get(
            combo.category, 9
        )
        return (
            maz_penalty,
            tuple(-part for part in version_parts) or (0,),
            category_order,
        )

    return sorted(combos, key=_sort_key)[0]


def _combo_ha_supported(category: str | None) -> bool | None:
    if category is None:
        return None
    return category in ("HighAvailability", "cluster")


def _fetch_rds_available_zones(client, region_id: str) -> dict:
    zones = _alicloud_api_call(
        lambda: client.describe_available_zones_with_options(
            rds_models.DescribeAvailableZonesRequest(
                engine=_RDS_ENGINE,
                engine_version="16.0",
                commodity_code=_RDS_COMMODITY,
                region_id=region_id,
            ),
            _rds_runtime(),
        )
    )
    return zones.body.to_map()


@cachier(hash_func=jsoned_hash, separate_files=True)
def _cached_fetch_rds_available_zones(region_id: str) -> dict:
    return _fetch_rds_available_zones(_rds_client(region_id), region_id)


def _list_rds_classes(client, region_id: str):
    return _alicloud_api_call(
        lambda: client.list_classes_with_options(
            rds_models.ListClassesRequest(
                engine=_RDS_ENGINE,
                commodity_code=_RDS_COMMODITY,
                order_type=_RDS_ORDER_TYPE,
                region_id=region_id,
            ),
            _rds_runtime(),
        )
    )


@cachier(hash_func=jsoned_hash, separate_files=True)
def _cached_list_rds_class_items(region_id: str) -> list[dict]:
    classes = _list_rds_classes(_rds_client(region_id), region_id)
    payload = classes.body.to_map()
    return _dig_list(payload, "Items", "ClassList") or _dig_list(payload, "Items")


def _list_rds_class_items(client, region_id: str) -> list[dict]:
    classes = _list_rds_classes(client, region_id)
    payload = classes.body.to_map()
    return _dig_list(payload, "Items", "ClassList") or _dig_list(payload, "Items")


def _rds_class_catalog(items: list[dict]) -> dict[str, dict]:
    catalog: dict[str, dict] = {}
    for item in items:
        class_code = item.get("ClassCode") or item.get("DBInstanceClass")
        if class_code:
            catalog[class_code] = item
    return catalog


def _available_rds_classes_by_combo(
    client, combo: _RdsPriceCombo, region_id: str
) -> dict[str, tuple[str, dict]]:
    merged: dict[str, dict[str, dict]] = {}
    for storage_type in combo.storage_types:
        response = _alicloud_api_call(
            lambda storage_type=storage_type: client.describe_available_classes_with_options(
                rds_models.DescribeAvailableClassesRequest(
                    engine=_RDS_ENGINE,
                    engine_version=combo.engine_version,
                    zone_id=combo.zone_id,
                    category=combo.category,
                    instance_charge_type=_RDS_PAY_TYPE,
                    dbinstance_storage_type=storage_type,
                    commodity_code=_RDS_COMMODITY,
                    order_type=_RDS_ORDER_TYPE,
                    region_id=region_id,
                ),
                _rds_runtime(),
            ),
            ignore_not_found=True,
        )
        if response is None:
            continue
        for item in _dig_list(
            response.body.to_map(), "DBInstanceClasses", "DBInstanceClass"
        ) or _dig_list(response.body.to_map(), "DBInstanceClasses"):
            class_code = item.get("DBInstanceClass") or item.get("ClassCode")
            if class_code:
                merged.setdefault(class_code, {})[storage_type] = item
    return {
        class_code: (next(iter(by_storage.keys())), next(iter(by_storage.values())))
        for class_code, by_storage in merged.items()
    }


def _describe_rds_database_price(
    client,
    combo: _RdsPriceCombo,
    class_code: str,
    storage_type: str,
    storage_gib: int,
    region_id: str,
) -> tuple[float | None, str | None]:
    response = _alicloud_api_call(
        lambda: client.describe_price_with_options(
            rds_models.DescribePriceRequest(
                engine=_RDS_ENGINE,
                engine_version=combo.engine_version,
                dbinstance_class=class_code,
                dbinstance_storage=storage_gib,
                quantity=1,
                pay_type=_RDS_PAY_TYPE,
                commodity_code=_RDS_COMMODITY,
                order_type=_RDS_ORDER_TYPE,
                zone_id=combo.zone_id,
                dbinstance_storage_type=storage_type,
                instance_used_type=0,
                region_id=region_id,
            ),
            _rds_runtime(),
        )
    )
    price_info = response.body.to_map().get("PriceInfo") or {}
    return _optional_float(price_info.get("TradePrice")), price_info.get("Currency")


def _postgres_storage_types(zones_payload: dict) -> list[str]:
    storage_types: set[str] = set()
    for combo in _postgres_price_combos(zones_payload):
        storage_types.update(combo.storage_types)
    return sorted(storage_types)


def _normalize_pg_engine_version(version: str) -> str:
    return str(version).split(".")[0]


def _parse_postgres_engine_versions(zones_payload: dict) -> list[str]:
    versions: set[str] = set()
    for zone in _postgres_zones(zones_payload):
        for engine in _dig_list(
            zone, "SupportedEngines", "SupportedEngine"
        ) or _dig_list(zone, "SupportedEngines"):
            engine_name = engine.get("Engine") or engine.get("engine")
            if engine_name and engine_name.lower() != _RDS_ENGINE.lower():
                continue
            for version_entry in _dig_list(
                engine, "SupportedEngineVersions", "SupportedEngineVersion"
            ) or _dig_list(engine, "SupportedEngineVersions"):
                version = version_entry.get("Version") or version_entry.get("version")
                if version:
                    versions.add(_normalize_pg_engine_version(str(version)))
    return sorted(versions)


def _postgres_engine_versions(client, region_id: str) -> list[str]:
    return _parse_postgres_engine_versions(
        _cached_call(_cached_fetch_rds_available_zones, region_id)
    )


def _inventory_databases_for_region(vendor, region, client) -> list[dict]:
    region_id = region.region_id
    rows = []

    def on_error():
        vendor.log(f"RDS database inventory failed for {region_id}", WARN)

    with sentry_capture_or_raise(vendor=vendor, on_error=on_error):
        zones_payload = _cached_call(_cached_fetch_rds_available_zones, region_id)
        engine_versions = _parse_postgres_engine_versions(zones_payload)
        combo = _pick_postgres_price_combo(_postgres_price_combos(zones_payload))
        available_by_class = (
            _available_rds_classes_by_combo(client, combo, region_id) if combo else {}
        )
        class_items = _cached_call(_cached_list_rds_class_items, region_id)
        for item in class_items:
            class_code = item.get("ClassCode") or item.get("DBInstanceClass")
            if not class_code:
                continue
            available_entry = available_by_class.get(class_code)
            available = available_entry[1] if available_entry else {}
            storage_range = available.get("DBInstanceStorageRange") or {}
            storage_min = storage_range.get("MinValue")
            storage_max = storage_range.get("MaxValue")
            rows.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "database_id": class_code,
                    "name": class_code,
                    "api_reference": class_code,
                    "display_name": class_code,
                    "engine": DatabaseEngine.POSTGRESQL,
                    "engine_versions": engine_versions,
                    "family": class_code.split(".")[1]
                    if "." in class_code
                    else class_code,
                    "vcpus": _parse_rds_vcpu(item.get("Cpu") or item.get("CpuCount")),
                    "memory_amount": _parse_rds_memory_amount(
                        item.get("MemoryClass") or item.get("Memory")
                    ),
                    "storage_size_min": int(storage_min)
                    if storage_min is not None
                    else None,
                    "storage_size_max": int(storage_max)
                    if storage_max is not None
                    else None,
                    "storage_type": None,
                    "ha_supported": _combo_ha_supported(combo.category)
                    if combo
                    else None,
                    "storage_autoscaling": (
                        storage_min is not None
                        and storage_max is not None
                        and float(storage_max) > float(storage_min)
                    )
                    if storage_range
                    else None,
                    "scheduled_backups": True,
                    "continuous_backups": None,
                }
            )
    return rows


def _inventory_database_prices_for_region(vendor, region, client) -> list[dict]:
    region_id = region.region_id
    items = []

    def on_error():
        vendor.log(f"RDS database pricing failed for {region_id}", WARN)

    with sentry_capture_or_raise(vendor=vendor, on_error=on_error):
        zones_payload = _cached_call(_cached_fetch_rds_available_zones, region_id)
        combo = _pick_postgres_price_combo(_postgres_price_combos(zones_payload))
        if combo is None:
            return items
        class_catalog = _rds_class_catalog(
            _cached_call(_cached_list_rds_class_items, region_id)
        )
        available_by_class = _available_rds_classes_by_combo(client, combo, region_id)
        price_cache: dict[tuple[str, str, int], tuple[float | None, str | None]] = {}
        for class_code, (storage_type, available) in available_by_class.items():
            class_meta = class_catalog.get(class_code, {})
            storage_range = available.get("DBInstanceStorageRange") or {}
            storage_gib = int(
                float(storage_range.get("MinValue") or _RDS_DEFAULT_STORAGE_GIB)
            )
            cache_key = (class_code, storage_type, storage_gib)
            if cache_key not in price_cache:
                fallback = (
                    _optional_float(class_meta.get("ReferencePrice")),
                    class_meta.get("Currency") or "USD",
                )

                def on_price_error(
                    key=cache_key,
                    fallback_price=fallback,
                    cache=price_cache,
                ):
                    cache[key] = fallback_price

                with sentry_capture_or_raise(vendor=vendor, on_error=on_price_error):
                    price_cache[cache_key] = _describe_rds_database_price(
                        client,
                        combo,
                        class_code,
                        storage_type,
                        storage_gib,
                        region_id,
                    )
            price, currency = price_cache[cache_key]
            if price is None:
                price = _optional_float(class_meta.get("ReferencePrice"))
                currency = class_meta.get("Currency") or currency or "USD"
            if price is None:
                continue
            items.append(
                {
                    "vendor_id": vendor.vendor_id,
                    "region_id": region_id,
                    "database_id": class_code,
                    "allocation": Allocation.ONDEMAND,
                    "unit": PriceUnit.HOUR,
                    "price": price,
                    "price_upfront": 0,
                    "price_tiered": [],
                    "currency": currency or "USD",
                }
            )
    return items


def _inventory_database_storages_for_region(vendor, region_id: str) -> list[str]:
    storage_types = []

    def on_error():
        vendor.log(f"RDS database storage inventory failed for {region_id}", WARN)

    with sentry_capture_or_raise(vendor=vendor, on_error=on_error):
        zones_payload = _cached_call(_cached_fetch_rds_available_zones, region_id)
        storage_types = _postgres_storage_types(zones_payload)
    return storage_types


def inventory_databases(vendor):
    if rds_models is None:
        vendor.progress_tracker.start_task(name="Fetching database(s)", total=None)
        vendor.progress_tracker.hide_task()
        return []
    rows = []
    rds_clients = _rds_clients(vendor)
    vendor.progress_tracker.start_task(
        name="Scanning region(s) for database(s)", total=len(vendor.regions)
    )

    def scan_region(region):
        try:
            return _inventory_databases_for_region(
                vendor, region, rds_clients[region.region_id]
            )
        finally:
            vendor.progress_tracker.advance_task()

    with ThreadPoolExecutor(max_workers=8) as executor:
        for part in executor.map(scan_region, vendor.regions):
            rows.extend(part)
    vendor.progress_tracker.hide_task()
    return merge_database_catalog_rows(rows)


def inventory_database_prices(vendor):
    if rds_models is None:
        vendor.progress_tracker.start_task(
            name="Fetching database_price(s)", total=None
        )
        vendor.progress_tracker.hide_task()
        return []
    items = []
    rds_clients = _rds_clients(vendor)
    vendor.progress_tracker.start_task(
        name="Scanning region(s) for database_price(s)", total=len(vendor.regions)
    )

    def scan_region(region):
        try:
            return _inventory_database_prices_for_region(
                vendor, region, rds_clients[region.region_id]
            )
        finally:
            vendor.progress_tracker.advance_task()

    with ThreadPoolExecutor(max_workers=8) as executor:
        for part in executor.map(scan_region, vendor.regions):
            items.extend(part)
    vendor.progress_tracker.hide_task()
    return items


def inventory_database_storages(vendor):
    if rds_models is None:
        vendor.progress_tracker.start_task(
            name="Fetching database_storage(s)", total=None
        )
        vendor.progress_tracker.hide_task()
        return []
    items = []
    vendor.progress_tracker.start_task(
        name="Scanning region(s) for database_storage(s)", total=len(vendor.regions)
    )

    def scan_region(region):
        try:
            return _inventory_database_storages_for_region(vendor, region.region_id)
        finally:
            vendor.progress_tracker.advance_task()

    storage_types: set[str] = set()
    with ThreadPoolExecutor(max_workers=8) as executor:
        for region_storage_types in executor.map(scan_region, vendor.regions):
            storage_types.update(region_storage_types)
    for storage_type in sorted(storage_types):
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "database_storage_id": storage_type,
                "name": storage_type,
                "description": storage_type,
                "scope": DatabaseStorageScope.DATA,
            }
        )
    vendor.progress_tracker.hide_task()
    return items


def inventory_database_storage_prices(vendor):
    vendor.progress_tracker.start_task(
        name="Fetching database_storage_price(s)", total=None
    )
    vendor.progress_tracker.hide_task()
    return []
