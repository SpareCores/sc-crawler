import json
import os
from functools import lru_cache

from aliyunsdkbssopenapi.request.v20171214 import DescribePricingModuleRequest
from aliyunsdkcore.acs_exception.exceptions import ClientException, ServerException
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.request import CommonRequest
from aliyunsdkecs.request.v20140526 import (
    DescribeInstanceTypesRequest,
    DescribePriceRequest,
    DescribeRegionsRequest,
    DescribeZonesRequest,
)

from ..logger import logger
from ..lookup import map_compliance_frameworks_to_vendor
from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    PriceUnit,
    StorageType,
)

ONE_REGION_QUERY = False
SKIP_CHINA = False
DEFAULT_REGION = "eu-central-1"

aliyun_region_coords = {
    # -------- Mainland China --------
    "cn-qingdao": {
        "city": "Qingdao",
        "lat": 36.0671,
        "lon": 120.3826,
        "country_id": "CN",
    },
    "cn-beijing": {
        "city": "Beijing",
        "lat": 39.9042,
        "lon": 116.4074,
        "country_id": "CN",
    },
    "cn-zhangjiakou": {
        "city": "Zhangjiakou",
        "lat": 40.8244,
        "lon": 114.8875,
        "country_id": "CN",
    },
    "cn-huhehaote": {
        "city": "Hohhot",
        "lat": 40.8426,
        "lon": 111.7490,
        "country_id": "CN",
    },
    "cn-wulanchabu": {
        "city": "Ulanqab",
        "lat": 41.0350,
        "lon": 113.1343,
        "country_id": "CN",
    },
    "cn-hangzhou": {
        "city": "Hangzhou",
        "lat": 30.2741,
        "lon": 120.1551,
        "country_id": "CN",
    },
    "cn-shanghai": {
        "city": "Shanghai",
        "lat": 31.2304,
        "lon": 121.4737,
        "country_id": "CN",
    },
    "cn-nanjing": {
        "city": "Nanjing",
        "lat": 32.0603,
        "lon": 118.7969,
        "country_id": "CN",
    },
    "cn-shenzhen": {
        "city": "Shenzhen",
        "lat": 22.5431,
        "lon": 114.0579,
        "country_id": "CN",
    },
    "cn-heyuan": {
        "city": "Heyuan",
        "lat": 23.7405,
        "lon": 114.7003,
        "country_id": "CN",
    },
    "cn-guangzhou": {
        "city": "Guangzhou",
        "lat": 23.1291,
        "lon": 113.2644,
        "country_id": "CN",
    },
    "cn-fuzhou": {
        "city": "Fuzhou",
        "lat": 26.0745,
        "lon": 119.2965,
        "country_id": "CN",
    },
    "cn-wuhan-lr": {
        "city": "Wuhan",
        "lat": 30.5928,
        "lon": 114.3055,
        "country_id": "CN",
    },
    "cn-chengdu": {
        "city": "Chengdu",
        "lat": 30.5728,
        "lon": 104.0668,
        "country_id": "CN",
    },
    # -------- Hong Kong --------
    "cn-hongkong": {
        "city": "Hong Kong",
        "lat": 22.3193,
        "lon": 114.1694,
        "country_id": "HK",
    },
    # -------- Asia Pacific --------
    "ap-northeast-1": {
        "city": "Tokyo",
        "lat": 35.6895,
        "lon": 139.6917,
        "country_id": "JP",
    },
    "ap-northeast-2": {
        "city": "Seoul",
        "lat": 37.5665,
        "lon": 126.9780,
        "country_id": "KR",
    },
    "ap-southeast-1": {
        "city": "Singapore",
        "lat": 1.3521,
        "lon": 103.8198,
        "country_id": "SG",
    },
    "ap-southeast-3": {
        "city": "Kuala Lumpur",
        "lat": 3.1390,
        "lon": 101.6869,
        "country_id": "MY",
    },
    "ap-southeast-6": {
        "city": "Manila",
        "lat": 14.5995,
        "lon": 120.9842,
        "country_id": "PH",
    },
    "ap-southeast-5": {
        "city": "Jakarta",
        "lat": 6.2088,
        "lon": 106.8456,
        "country_id": "ID",
    },
    "ap-southeast-7": {
        "city": "Bangkok",
        "lat": 13.7563,
        "lon": 100.5018,
        "country_id": "TH",
    },
    # -------- United States --------
    "us-east-1": {
        "city": "Virginia",
        "lat": 38.0293,
        "lon": -78.4767,
        "country_id": "US",
    },
    "us-west-1": {
        "city": "Silicon Valley",
        "lat": 37.3875,
        "lon": -122.0575,
        "country_id": "US",
    },
    # -------- North America --------
    "na-south-1": {
        "city": "Mexico City",
        "lat": 19.4326,
        "lon": -99.1332,
        "country_id": "MX",
    },
    # -------- Europe --------
    "eu-west-1": {"city": "London", "lat": 51.5074, "lon": -0.1278, "country_id": "GB"},
    "eu-central-1": {
        "city": "Frankfurt",
        "lat": 50.1109,
        "lon": 8.6821,
        "country_id": "DE",
    },
    # -------- Middle East --------
    "me-east-1": {"city": "Dubai", "lat": 25.2048, "lon": 55.2708, "country_id": "AE"},
    "me-central-1": {
        "city": "Riyadh",
        "lat": 24.7136,
        "lon": 46.6753,
        "country_id": "SA",
    },
}


@lru_cache(maxsize=1)
def get_client():
    """
    Creates a client object using the Aliyun user's access key and secret stored in the ALIYUN_ACCESS_KEY and ALIYUN_SECRET environment variables. ALIYUN_REGION will become the default region. Returns a client object.
    """
    return AcsClient(
        os.environ["ALIYUN_ACCESS_KEY"],
        os.environ["ALIYUN_SECRET"],
        os.environ["ALIYUN_REGION"],
    )


def get_regions(one_region_query=False):
    """
    Gathers the available regions in a list format. Uses the standard client object generated by the "get_client" function. Returns a dictionary with region info.

    NOTE: Due to extensive runtime issues the option to return just one signle region was added. If "ONE_REGION_QUERY" is True, this function only returns the default region, which is eu-central-1 (Frankfurt).
    """
    client = get_client()
    if one_region_query == True:
        region_info_in_list = {
            "RequestId": "148E7C7E-8308-3D63-9BC0-1C1002B081C5",
            "Regions": {
                "Region": [
                    {
                        "RegionId": DEFAULT_REGION,
                        "RegionEndpoint": "ecs.{}.aliyuncs.com".format(DEFAULT_REGION),
                        "LocalName": "\u5fb7\u56fd\uff08\u6cd5\u5170\u514b\u798f\uff09",
                    }
                ]
            },
        }
    else:
        request = DescribeRegionsRequest.DescribeRegionsRequest()
        response = client.do_action_with_exception(request)
        region_info_in_list = json.loads(response.decode("utf-8"))
    return region_info_in_list


def get_zones(tempcl):
    """
    Gathers the zones available in given region. Takes a client object as a parameter. Returns a dictionary with zone info.
    """
    # client = get_client()
    region_list = get_regions(one_region_query=ONE_REGION_QUERY)
    request = DescribeZonesRequest.DescribeZonesRequest()
    response = tempcl.do_action_with_exception(request)
    zone_info_in_list = json.loads(response.decode("utf-8"))
    return zone_info_in_list


def get_instance_types(tempclient):
    """
    Gathers the available ECS instance types available in the given region. Receives a client object as a parameter. Returns a dictionary with instance type info.
    """
    request = DescribeInstanceTypesRequest.DescribeInstanceTypesRequest()
    response = tempclient.do_action_with_exception(request)
    instance_type_info_in_list = json.loads(response.decode("utf-8"))
    return instance_type_info_in_list


def get_disk_capabilities(tempclient):
    """
    Gathers information on pricing data on modules related to ECS instances. Returns a dictionary with disk info.
    """
    req = DescribePricingModuleRequest.DescribePricingModuleRequest()
    req.set_ProductCode("ecs")
    req.set_SubscriptionType("PayAsYouGo")
    response = tempclient.do_action_with_exception(req)
    return json.loads(response.decode("utf-8"))


def get_instance_price(tempclient, instance_type):
    """
    Gathers information on pricing data of ECS instances. Returns a dictionary with price info. (Deprecated)
    """
    request = DescribePriceRequest.DescribePriceRequest()
    request.set_InstanceType(instance_type)
    request.set_SystemDiskCategory("cloud_ssd")
    request.set_SystemDiskSize(50)  # above minimum system disk size
    response = tempclient.do_action_with_exception(request)
    return json.loads(response.decode("utf-8"))


def get_instance_price_with_sku_price_list(tempclient, next_token=None):
    """
    Gathers information on pricing data of ECS instances by using CommonRequest, targeting the QuerySkuPriceList endpoint. Returns a dictionary with price info of 50 instances, and the query gets called again until the next_token is not present in the previous query.
    """
    request = CommonRequest()
    request.set_accept_format("json")
    request.set_domain("business.ap-southeast-1.aliyuncs.com")
    request.set_version("2017-12-14")
    request.set_action_name("QuerySkuPriceList")
    request.set_method("GET")

    request.add_query_param("CommodityCode", "ecs_intl")
    request.add_query_param("PriceEntityCode", "instance_type")
    request.add_query_param("PageSize", "50")
    request.add_query_param("Lang", "en")

    if next_token:
        request.add_query_param("NextPageToken", next_token)
    try:
        response = tempclient.do_action_with_exception(request)
    except ServerException as se:
        logger.error("unexpected error while getting sku price.")
        logger.debug(se)
        return {}

    return json.loads(response.decode("utf-8"))


def inventory_compliance_frameworks(vendor):
    """
    Lists out the compliance frameworks implemented by Alibaba cloud. All the information gathered below were taken from the official site dedicated for this topic. <https://www.alibabacloud.com/en/trust-center/compliance>
    """
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id,
        [
            # global
            "csa-star",  # CSA STAR certification
            "iso27001",  # ISMS standard
            "iso20000",  # IT SMS standard
            "iso22301",  # BCMS standard
            "iso9001",  # QMS standard
            "iso27017",  # IT security techniques, code practice for cloud services
            "iso27018",  # IT security techniques, code practice for cloud services
            "iso27701",  # IT security techniques, code practice for PII
            "iso29151",  # security techniques extrnsion
            "iso29151",  # IT security techniques
            "iso27799",  # health information security management guideline
            "iso27040",  # storage security guidance
            "pci_3ds",  # PCI 3DS
            "soc1",  # SOC 1 report
            "soc2",  # SOC 2 report
            "soc3",  # SOC 3 report
            # regional
            "dptm",  # DPTM (Singapore) - data protection trustmark
            "aic4",  # AIC4 (Germany) - AI cloud service compliance creiteria catalog
            "gdpr",  # GDPR - European Union General Data Protection Regulation
            "nist",  # NIST SP 800-53 / NIST CSF - U.S. National Institute of Standards and Technology frameworks
            "mlps_2",  # MLPS 2.0 (China) - classified protection of cybersecurity
            "itss",  # ITSS (China) - ITSS cloud computing service capability assessment
            "c5",  # C5 (Germany) - Cloud Computing Compliance Controls Catalog
            "mtcs",  # MTCS (Singapore) - Multi-Tier Cloud Security Standard
            "trucs",  # TRUCS (China) - Certification for Cloud Computing Services
            "nisc",  # NISC (Japan) - National center of Incident readiness and Strategy for Cybersecurity
            "ctm",  # CTM (Singapore) - Cyber Trust Mark certification
            "k-isms",  # K-ISMS (Korea) - Korea Information Security Management System certification
            # industry
            "gxp",  # GxP (USA) - Good Clinical, Laboratory and Manufacturing Practices
            "tisax",  # TISAX (Germany) - Trusted Information Secrurity Assessment Exchange
            "hipaa",  # HIPAA (USA) - Health Insurace Portability and Accountibility Act
            "mpa",  # MPA (USA) - The Motion Picture Association
            "sec_rule_17a",  # SEC Rule 17a (USA) - Secrutites and Exchange Commission, Rule 17a
            "ospar",  # OSPAR (Singapore) - Outsourced Service Provider Audit Report
            "ferpa"  # FERPA (USA) - The Family Education Rights and Privacy Act
            "coppa",  # COPPA (USA) - The Children's Online Privacy Protection Act
            "dpp"  # DPP - Prduction and Broadcast - Digital Production Partnership (DPP) Committed to Security programme
            "fisc"  # FISC (Japan) - The Center for Financial Industry Information Systems
            # data protection
            "gdpr",  # GDPR (EU) - The European Union General Data Protection Regulation
            "eu-cloud-coc",  # EU Cloud CoC (EU) - The Eurpoean Union Cloud Code of Conduct
            "pdpa",  # PDPA (Singapore and Malaysia) - Personal Data Protection Act
            "pdpo",  # PDPO (Hong Kong) - Personal Data (Privacy) Ordinance
            "cbpr",  # APEC CBPR (Singapore) - The APEC Cross Border Privacy Rules
            "prp",  # APEC PRP (Singapore) - The APEC Privacy Recognition for Processors
        ],
    )


def inventory_regions(vendor):
    """
    Puts together the list containing information about the available regions in the Alibaba Cloud service.
    """
    items = []
    region_info_in_list = get_regions(one_region_query=ONE_REGION_QUERY)
    for region in region_info_in_list.get("Regions").get("Region"):
        logger.info(
            "Adding region {rid} to database...".format(rid=region.get("RegionId"))
        )
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.get("RegionId"),
                "name": region.get("LocalName"),
                "api_reference": region.get("RegionId"),
                "display_name": region.get("LocalName"),
                "aliases": [],
                "country_id": aliyun_region_coords.get(region.get("RegionId")).get(
                    "country_id"
                ),
                "state": None,  # not available
                "city": aliyun_region_coords.get(region.get("RegionId")).get("city"),
                "address_line": None,  # not available
                "zip_code": None,  # not available
                "lon": aliyun_region_coords.get(region.get("RegionId")).get("lon"),
                "lat": aliyun_region_coords.get(region.get("RegionId")).get("lat"),
                "founding_year": None,  # not available
                "green_energy": None,  # not available
            }
        )
    return items


def inventory_zones(vendor, skip_china=SKIP_CHINA):
    """
    Puts together the list containing information about the available zones for each region in the Alibaba Cloud service. Mainland Chinese regions were inaccessible due to the existence of the Great Firewall, so regions with a 'cn' region code are ignored while creating the list.
    """
    items = []
    region_info_in_list = get_regions(one_region_query=ONE_REGION_QUERY)
    for region in region_info_in_list.get("Regions").get("Region"):
        # a try block with a specific exception for timeout would be probably better, but why should we wait for the timeout
        if skip_china:
            if "cn-" in region.get("RegionId"):
                logger.info(
                    "Region {rid} is inaccessible, skipping zones...".format(
                        rid=region.get("RegionId")
                    )
                )
                continue  # chinese regions are not accessible from here
        else:
            try:
                tempclient = AcsClient(
                    os.environ["ALIYUN_ACCESS_KEY"],
                    os.environ["ALIYUN_SECRET"],
                    region.get("RegionId"),
                )

                zone_info_in_list = get_zones(tempcl=tempclient)

                for zone in zone_info_in_list.get("Zones").get("Zone"):
                    logger.debug(
                        "Getting zone {} in region {}...".format(
                            region.get("RegionId"), zone.get("ZoneId")
                        )
                    )
                    items.append(
                        {
                            "vendor_id": vendor.vendor_id,
                            "region_id": region.get("RegionId"),
                            "zone_id": zone.get("ZoneId"),
                            "name": zone.get("ZoneId"),
                            "api_reference": zone.get("ZoneId"),
                            "display_name": zone.get("ZoneId"),
                        }
                    )
            except ClientException as ce:
                logger.debug(
                    "Failed to query region {rid}".format(rid=region.get("RegionId"))
                )
                logger.debug(ce)

    return items


def inventory_servers(vendor):
    """
    Puts together the list containing information about the hardware capabilities of each ECS type in the Alibaba Cloud service.
    """
    items = []
    tempclient = AcsClient(
        os.environ["ALIYUN_ACCESS_KEY"],
        os.environ["ALIYUN_SECRET"],
        os.environ["ALIYUN_REGION"],
    )
    instance_info_in_list = get_instance_types(tempclient)
    for instancetype in instance_info_in_list.get("InstanceTypes").get("InstanceType"):
        cpu_arch_info = instancetype.get("CpuArchitecture").upper()
        if cpu_arch_info == "X86":
            set_cpu_arch = CpuArchitecture.X86_64
        elif cpu_arch_info == "ARM":
            set_cpu_arch = CpuArchitecture.ARM64
        else:
            set_cpu_arch = None

        logger.debug(
            "Adding instance {iid} to database...".format(
                iid=instancetype.get("InstanceTypeId")
            )
        )
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "server_id": instancetype.get("InstanceTypeId"),
                "name": instancetype.get("InstanceTypeId"),
                "api_reference": instancetype.get("InstanceTypeId"),
                "display_name": instancetype.get("InstanceTypeId"),
                "description": "{ifam}, {icat}".format(
                    icat=instancetype.get("InstanceCategory"),
                    ifam=instancetype.get("InstanceFamilyLevel"),
                ),
                "family": instancetype.get("InstanceTypeFamily"),
                "vcpus": instancetype.get("CpuCoreCount"),
                "hypervisor": "KVM",
                "cpu_allocation": CpuAllocation.DEDICATED,
                "cpu_cores": instancetype.get("CpuCoreCount", 0),
                "cpu_speed": instancetype.get("CpuSpeedFrequency"),
                "cpu_architecture": set_cpu_arch,
                "cpu_manufacturer": None,
                "cpu_family": None,
                "cpu_model": instancetype.get("PhysicalProcessorModel"),
                "cpu_l1_cache": None,
                "cpu_l2_cache": None,
                "cpu_l3_cache": None,
                "cpu_flags": [],
                "cpus": [],
                "memory_amount": int((instancetype.get("MemorySize") * 1024)),
                "memory_generation": None,
                "memory_speed": None,
                "memory_ecc": None,
                "gpu_count": instancetype.get("GPUAmount", 0),
                "gpu_memory_min": None,
                "gpu_memory_total": None,
                "gpu_manufacturer": None,
                "gpu_family": None,
                "gpu_model": instancetype.get("GPUSpec"),
                "gpus": [],
                "storage_size": 0,
                "storage_type": None,
                "storages": [],
                "network_speed": None,
                "inbound_traffic": 0,
                "outbound_traffic": 0,
                "ipv4": 0,
            }
        )
    return items


def inventory_server_prices(vendor):
    """
    Puts together the list containing information about the hardware capabilities of each ECS type in the Alibaba Cloud service. These are hourly, pay-as-you-go prices.

    """
    items = []

    tempclient = get_client()

    next_token = None
    page = 1
    while True:
        sku_price_data = get_instance_price_with_sku_price_list(
            tempclient, next_token=next_token
        )
        logger.debug(
            "Getting page {pagenum} of QuerySkuPriceList ...".format(pagenum=page)
        )
        for sku in sku_price_data.get("Data").get("SkuPricePage").get("SkuPriceList"):
            try:
                logger.debug(
                    "Adding instance info - region_id: {region_id}, instance type: {itype}, price: {price} {curr}".format(
                        region_id=sku["SkuFactorMap"]["vm_region_no"],
                        itype=sku["SkuFactorMap"]["instance_type"],
                        price=sku["CskuPriceList"][0]["Price"],
                        curr=sku["CskuPriceList"][0]["Currency"],
                    )
                )
                items.append(
                    {
                        "vendor_id": vendor.vendor_id,
                        "region_id": sku.get("SkuFactorMap").get("vm_region_no"),
                        "zone_id": "all zones",
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
            except ServerException as se:
                logger.debug(
                    "Failed to add instance info - region_id: {region_id}, instance type: {itype}, price: {price} {curr}".format(
                        region_id=sku["SkuFactorMap"]["vm_region_no"],
                        itype=sku["SkuFactorMap"]["instance_type"],
                        price=sku["CskuPriceList"][0]["Price"],
                        curr=sku["CskuPriceList"][0]["Currency"],
                    )
                )
                logger.debug(se)
        # Safely extract next token if present
        next_token = (
            sku_price_data.get("Data", {}).get("SkuPricePage", {}).get("NextPageToken")
        )

        if not next_token:
            logger.debug(
                "No more QuerySkuPriceList pages or response json is missing Data — stopping query."
            )
            break

        page += 1

    return items


def inventory_server_prices_spot(vendor):
    # TODO: implement later.

    return []


def inventory_storages(vendor):
    """
    Puts together a list on hardware information related to different disk type choices available to be attached to an ECS instance. Most of the information is not supplied by the API, so instead this information is manually gathered and hardcoded based on the official information available in the related section of the user guide pages. MB/s is converted to Mb/sec to store information consistent to data supplied by the AWS module.
    <https://www.alibabacloud.com/help/en/ecs/user-guide/essds>
    """

    items = []

    # hardcoded, because API does not give back this information. MB/s converted to Mb/s
    # source: https://www.alibabacloud.com/help/en/ecs/user-guide/essds

    disk_info = [
        {
            "name": "cloud_essd-pl0",
            "min_size": 1,
            "max_size": 65536,
            "max_iop": 10000,
            "max_tp": 1440,
            "info": "Enterprise SSD with Performance level 0.",
        },
        {
            "name": "cloud_essd-pl1",
            "min_size": 20,
            "max_size": 65536,
            "max_iop": 50000,
            "max_tp": 2800,
            "info": "Enterprise SSD with Performance level 1.",
        },
        {
            "name": "cloud_essd-pl2",
            "min_size": 461,
            "max_size": 65536,
            "max_iop": 100000,
            "max_tp": 6000,
            "info": "Enterprise SSD with Performance level 2.",
        },
        {
            "name": "cloud_essd-pl3",
            "min_size": 1261,
            "max_size": 65536,
            "max_iop": 1000000,
            "max_tp": 32000,
            "info": "Enterprise SSD with Performance level 3.",
        },
        {
            "name": "cloud_ssd",
            "min_size": 20,
            "max_size": 32768,
            "max_iop": 20000,
            "max_tp": 256,
            "info": "Standard SSD.",
        },
        {
            "name": "cloud_efficiency",
            "min_size": 20,
            "max_size": 32768,
            "max_iop": 3000,
            "max_tp": 80,
            "info": "Ultra Disk, older generation.",
        },
        {
            "name": "cloud",
            "min_size": 5,
            "max_size": 2000,
            "max_iop": 300,
            "max_tp": 40,
            "info": "Lowest cost HDD.",
        },
    ]

    for disk in disk_info:
        logger.debug(
            "Adding information to database on disk type {}...".format(disk.get("name"))
        )
        items.append(
            {
                "storage_id": disk.get("name"),
                "vendor_id": vendor.vendor_id,
                "name": disk.get("name"),
                "description": disk.get("info"),
                "storage_type": StorageType.HDD
                if disk.get("name") == "cloud"
                else StorageType.SSD,
                "max_iops": disk.get("max_iop"),
                "max_throughput": disk.get("max_tp"),
                "min_size": disk.get("min_size"),
                "max_size": disk.get("max_size"),
            }
        )
    return items


def inventory_storage_prices(vendor, skip_china=SKIP_CHINA):
    """
    Puts together a list of storage prices. As storage is treated as a separate pricing package, the implementation assumes an instance type which is common, and can be found in any data center. Then it cycles through the hardcoded storage types.

    Notes:
    - cloud_efficiency: Missing in new regions
    - cloud (basic): Missing in many regions
    - ephemeral_ssd: Missing in 95% of regions
    - cloud_essd PL2/PL3: Missing in some small regions
    - elastic_ephemeral_disk: Only available on local NVMe instance types (not queried here)
    """
    items = []
    tempclient = get_client()

    DEFAULT_INSTANCE_TYPE = "ecs.c6.large"  # common instance, available in most regions. required for query.
    options_system_disk_category = [
        "cloud",
        "cloud_efficiency",
        "cloud_ssd",
        "ephemeral_ssd",
        "cloud_essd",
        "cloud_auto",
    ]
    options_essd_disk_performance_level = ["PL0", "PL1", "PL2", "PL3"]

    # cycling through regions, so we can get region-based data. If one region query is true, it only returns the default region.
    region_info_in_list = get_regions(one_region_query=ONE_REGION_QUERY)
    for region in region_info_in_list.get("Regions").get("Region"):
        # a try block with a specific exception for timeout would be probably better, but why should we wait for the timeout

        if skip_china:
            if "cn-" in region.get("RegionId"):
                continue  # chinese regions are not accessible from here
        else:
            tempclient = AcsClient(
                os.environ["ALIYUN_ACCESS_KEY"],
                os.environ["ALIYUN_SECRET"],
                region.get("RegionId"),
            )
            for disk in options_system_disk_category:
                request = DescribePriceRequest.DescribePriceRequest()
                request.set_PriceUnit("Hour")
                request.set_InstanceType(DEFAULT_INSTANCE_TYPE)
                request.set_DataDisk1Size(
                    2000
                )  # PL3 disks require a minimum of 1,261 GiB
                request.set_DataDisk1Category(disk)
                if disk == "cloud_essd":
                    for pl in options_essd_disk_performance_level:
                        request.set_DataDisk1PerformanceLevel(pl)
                        try:
                            response = tempclient.do_action_with_exception(request)
                            respone_dict = json.loads(response.decode("utf-8"))

                            for dti in (
                                respone_dict.get("PriceInfo")
                                .get("Price")
                                .get("DetailInfos")
                                .get("DetailInfo")
                            ):
                                if (
                                    dti.get("Resource") == "systemDisk"
                                    or dti.get("Resource") == "dataDisk"
                                ):
                                    items.append(
                                        {
                                            "vendor_id": vendor.vendor_id,
                                            "region_id": tempclient.get_region_id(),
                                            "storage_id": disk + "-" + pl,
                                            "unit": PriceUnit.GB_MONTH,
                                            "price": dti.get("TradePrice"),
                                            "currency": respone_dict.get("PriceInfo")
                                            .get("Price")
                                            .get("Currency"),
                                        }
                                    )
                                    logger.debug(
                                        "Successfully added disk info - Region: {tcl}, disk: {disk}, size: {size}, pl: {pl}".format(
                                            tcl=tempclient.get_region_id(),
                                            disk=disk,
                                            size=2000,
                                            pl=pl,
                                        )
                                    )
                        except ServerException as se:
                            logger.debug(se)
                            logger.debug(
                                "Failed to add disk info - Region: {tcl}, disk: {disk}, size: {size}, pl: {pl}".format(
                                    tcl=tempclient.get_region_id(),
                                    disk=disk,
                                    size=2000,
                                    pl=pl,
                                )
                            )
                            try:
                                if "OperationDenied.PerformanceLevelNotMatch" in str(
                                    se.get_error_code()
                                ):
                                    logger.debug(
                                        "Error indicates that this zone is likely not supporting this disk type."
                                    )
                                elif "InvalidDataDiskCategory.ValueNotSupported" in str(
                                    se.get_error_code()
                                ):
                                    logger.debug(
                                        "Error indicates likely invalid region / disk combination."
                                    )
                            except ServerException as se:
                                logger.debug(
                                    "Second error within the same cycle. This should not be here. {se}"
                                )
                        except ClientException as ce:
                            logger.debug(
                                "Failed to query region {rid}".format(
                                    rid=region.get("RegionId")
                                )
                            )
                            logger.debug(ce)

                else:
                    try:
                        response = tempclient.do_action_with_exception(request)
                        respone_dict = json.loads(response.decode("utf-8"))
                        for dti in (
                            respone_dict.get("PriceInfo")
                            .get("Price")
                            .get("DetailInfos")
                            .get("DetailInfo")
                        ):
                            if (
                                dti.get("Resource") == "systemDisk"
                                or dti.get("Resource") == "dataDisk"
                            ):
                                items.append(
                                    {
                                        "vendor_id": vendor.vendor_id,
                                        "region_id": tempclient.get_region_id(),
                                        "storage_id": disk,
                                        "unit": PriceUnit.GB_MONTH,
                                        "price": dti.get("TradePrice"),
                                        "currency": respone_dict.get("PriceInfo")
                                        .get("Price")
                                        .get("Currency"),
                                    }
                                )
                                logger.debug(
                                    "Successfully added disk info - Region: {tcl}, disk: {disk}, size: {size}".format(
                                        tcl=tempclient.get_region_id(),
                                        disk=disk,
                                        size=2000,
                                    )
                                )
                    except ServerException as se:
                        logger.debug(se)
                        logger.debug(
                            "Failed to add disk info - Region: {tcl}, disk: {disk}, size: {size}".format(
                                tcl=tempclient.get_region_id(), disk=disk, size=2000
                            )
                        )
                    except ClientException as ce:
                        logger.debug(
                            "Failed to query region {rid}".format(
                                rid=region.get("RegionId")
                            )
                        )
                        logger.debug(ce)

    return items


def inventory_traffic_prices(vendor):
    # TODO: implement later.
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "region_id": ,
    #             "price": ,
    #             "price_tiered": [],
    #             "currency": "USD",
    #             "unit": PriceUnit.GB_MONTH,
    #             "direction": TrafficDirection....,
    #         }
    #     )
    return items


def inventory_ipv4_prices(vendor):
    # TODO: implement later.
    items = []
    # for price in []:
    #     items.append(
    #         {
    #             "vendor_id": vendor.vendor_id,
    #             "region_id": ,
    #             "price": ,
    #             "currency": "USD",
    #             "unit": PriceUnit.MONTH,
    #         }
    #     )
    return items
