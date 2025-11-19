import os, json
from functools import cache, lru_cache
from ..lookup import map_compliance_frameworks_to_vendor

from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ClientException
from aliyunsdkcore.acs_exception.exceptions import ServerException
#from aliyunsdkecs.request.v20140526 import DescribeInstancesRequest
from aliyunsdkecs.request.v20140526 import DescribeRegionsRequest, DescribeZonesRequest, DescribeInstanceTypesRequest, DescribePriceRequest
from aliyunsdkbssopenapi.request.v20171214 import DescribePricingModuleRequest

from ..table_fields import (
    Allocation,
    CpuAllocation,
    CpuArchitecture,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)

aliyun_region_coords = {
    # -------- Mainland China --------
    "cn-qingdao":       {"city": "Qingdao",       "lat": 36.0671, "lon": 120.3826, "country_id": "CN"},
    "cn-beijing":       {"city": "Beijing",       "lat": 39.9042, "lon": 116.4074, "country_id": "CN"},
    "cn-zhangjiakou":   {"city": "Zhangjiakou",   "lat": 40.8244, "lon": 114.8875, "country_id": "CN"},
    "cn-huhehaote":     {"city": "Hohhot",        "lat": 40.8426, "lon": 111.7490, "country_id": "CN"},
    "cn-wulanchabu":    {"city": "Ulanqab",       "lat": 41.0350, "lon": 113.1343, "country_id": "CN"},
    "cn-hangzhou":      {"city": "Hangzhou",      "lat": 30.2741, "lon": 120.1551, "country_id": "CN"},
    "cn-shanghai":      {"city": "Shanghai",      "lat": 31.2304, "lon": 121.4737, "country_id": "CN"},
    "cn-nanjing":       {"city": "Nanjing",       "lat": 32.0603, "lon": 118.7969, "country_id": "CN"},
    "cn-shenzhen":      {"city": "Shenzhen",      "lat": 22.5431, "lon": 114.0579, "country_id": "CN"},
    "cn-heyuan":        {"city": "Heyuan",        "lat": 23.7405, "lon": 114.7003, "country_id": "CN"},
    "cn-guangzhou":     {"city": "Guangzhou",     "lat": 23.1291, "lon": 113.2644, "country_id": "CN"},
    "cn-fuzhou":        {"city": "Fuzhou",        "lat": 26.0745, "lon": 119.2965, "country_id": "CN"},
    "cn-wuhan-lr":      {"city": "Wuhan",         "lat": 30.5928, "lon": 114.3055, "country_id": "CN"},
    "cn-chengdu":       {"city": "Chengdu",       "lat": 30.5728, "lon": 104.0668, "country_id": "CN"},

    # -------- Hong Kong --------
    "cn-hongkong":      {"city": "Hong Kong",     "lat": 22.3193, "lon": 114.1694, "country_id": "HK"},

    # -------- Asia Pacific --------
    "ap-northeast-1":   {"city": "Tokyo",         "lat": 35.6895, "lon": 139.6917, "country_id": "JP"},
    "ap-northeast-2":   {"city": "Seoul",         "lat": 37.5665, "lon": 126.9780, "country_id": "KR"},
    "ap-southeast-1":   {"city": "Singapore",     "lat": 1.3521,  "lon": 103.8198, "country_id": "SG"},
    "ap-southeast-3":   {"city": "Kuala Lumpur",  "lat": 3.1390,  "lon": 101.6869, "country_id": "MY"},
    "ap-southeast-6":   {"city": "Manila",        "lat": 14.5995, "lon": 120.9842, "country_id": "PH"},
    "ap-southeast-5":   {"city": "Jakarta",       "lat": 6.2088,  "lon": 106.8456, "country_id": "ID"},
    "ap-southeast-7":   {"city": "Bangkok",       "lat": 13.7563, "lon": 100.5018, "country_id": "TH"},

    # -------- United States --------
    "us-east-1":        {"city": "Virginia",      "lat": 38.0293, "lon": -78.4767, "country_id": "US"},
    "us-west-1":        {"city": "Silicon Valley","lat": 37.3875, "lon": -122.0575,"country_id": "US"},

    # -------- North America --------
    "na-south-1":       {"city": "Mexico City",   "lat": 19.4326, "lon": -99.1332, "country_id": "MX"},

    # -------- Europe --------
    "eu-west-1":        {"city": "London",        "lat": 51.5074, "lon": -0.1278, "country_id": "GB"},
    "eu-central-1":     {"city": "Frankfurt",     "lat": 50.1109, "lon": 8.6821, "country_id": "DE"},

    # -------- Middle East --------
    "me-east-1":        {"city": "Dubai",         "lat": 25.2048, "lon": 55.2708, "country_id": "AE"},
    "me-central-1":     {"city": "Riyadh",        "lat": 24.7136, "lon": 46.6753, "country_id": "SA"}
}



@lru_cache(maxsize=1)
def get_client():
    return AcsClient(
        os.environ["ALIYUN_ACCESS_KEY"],
        os.environ["ALIYUN_SECRET"],
        os.environ["ALIYUN_REGION"]
    )


def get_regions():
    client = get_client()
    request = DescribeRegionsRequest.DescribeRegionsRequest()
    response = client.do_action_with_exception(request)
    region_info_in_list = json.loads(response.decode("utf-8")) 
    return region_info_in_list

def get_zones(tempcl):
    #client = get_client()
    region_list = get_regions()
    request = DescribeZonesRequest.DescribeZonesRequest()
    response = tempcl.do_action_with_exception(request)
    zone_info_in_list = json.loads(response.decode("utf-8")) 
    return zone_info_in_list

def get_instance_types():
    client = get_client()
    request = DescribeInstanceTypesRequest.DescribeInstanceTypesRequest()
    response = client.do_action_with_exception(request)
    instance_type_info_in_list = json.loads(response.decode("utf-8")) 
    return instance_type_info_in_list

def get_disk_capabilities(tempclient):
    req = DescribePricingModuleRequest.DescribePricingModuleRequest()
    req.set_ProductCode("ecs")
    req.set_SubscriptionType("PayAsYouGo")
    response = tempclient.do_action_with_exception(req)
    return json.loads(response.decode("utf-8"))

def get_instance_price(tempclient, instance_type):

    request = DescribePriceRequest.DescribePriceRequest()
    request.set_InstanceType(instance_type)
    #request.set_RegionId(region)
    #request.set_PriceUnit("Hour")  # required
    #request.set_SystemDiskCategory("cloud")

    response = tempclient.do_action_with_exception(request)
    return json.loads(response.decode("utf-8"))

def inventory_compliance_frameworks(vendor):
    # source: https://www.alibabacloud.com/en/trust-center/compliance
    return map_compliance_frameworks_to_vendor(vendor.vendor_id, 
        [
            # global
            "csa-star", # CSA STAR certification
            "iso27001", # ISMS standard
            "iso20000", # IT SMS standard
            "iso22301", # BCMS standard
            "iso9001", # QMS standard
            "iso27017", # IT security techniques, code practice for cloud services
            "iso27018", # IT security techniques, code practice for cloud services
            "iso27701", # IT security techniques, code practice for PII
            "iso29151", # security techniques extrnsion
            "iso29151", # IT security techniques
            "iso27799", # health information security management guideline
            "iso27040", # storage security guidance
            "pci_3ds", # PCI 3DS
            "soc1", # SOC 1 report
            "soc2", # SOC 2 report
            "soc3", # SOC 3 report
            # regional 
            "dptm", # DPTM (Singapore) - data protection trustmark
            "aic4", # AIC4 (Germany) - AI cloud service compliance creiteria catalog
            "gdpr", # GDPR - European Union General Data Protection Regulation
            "nist", # NIST SP 800-53 / NIST CSF - U.S. National Institute of Standards and Technology frameworks
            "mlps_2", # MLPS 2.0 (China) - classified protection of cybersecurity
            "itss", # ITSS (China) - ITSS cloud computing service capability assessment
            "c5", # C5 (Germany) - Cloud Computing Compliance Controls Catalog
            "mtcs", # MTCS (Singapore) - Multi-Tier Cloud Security Standard
            "trucs", # TRUCS (China) - Certification for Cloud Computing Services
            "nisc", # NISC (Japan) - National center of Incident readiness and Strategy for Cybersecurity
            "ctm", # CTM (Singapore) - Cyber Trust Mark certification
            "k-isms", # K-ISMS (Korea) - Korea Information Security Management System certification
            # industry
            "gxp", # GxP (USA) - Good Clinical, Laboratory and Manufacturing Practices
            "tisax", # TISAX (Germany) - Trusted Information Secrurity Assessment Exchange
            "hipaa", # HIPAA (USA) - Health Insurace Portability and Accountibility Act
            "mpa", # MPA (USA) - The Motion Picture Association
            "sec_rule_17a", # SEC Rule 17a (USA) - Secrutites and Exchange Commission, Rule 17a
            "ospar", #OSPAR (Singapore) - Outsourced Service Provider Audit Report
            "ferpa" # FERPA (USA) - The Family Education Rights and Privacy Act
            "coppa", # COPPA (USA) - The Children's Online Privacy Protection Act
            "dpp" # DPP - Prduction and Broadcast - Digital Production Partnership (DPP) Committed to Security programme
            "fisc" # FISC (Japan) - The Center for Financial Industry Information Systems
            # data protection
            "gdpr", # GDPR (EU) - The European Union General Data Protection Regulation
            "eu-cloud-coc", # EU Cloud CoC (EU) - The Eurpoean Union Cloud Code of Conduct
            "pdpa", # PDPA (Singapore and Malaysia) - Personal Data Protection Act 
            "pdpo", # PDPO (Hong Kong) - Personal Data (Privacy) Ordinance
            "cbpr", # APEC CBPR (Singapore) - The APEC Cross Border Privacy Rules
            "prp" # APEC PRP (Singapore) - The APEC Privacy Recognition for Processors            
        ]
    )


def inventory_regions(vendor):
    items = []
    region_info_in_list = get_regions()
    for region in region_info_in_list.get("Regions").get("Region"):   
        #print("REGION: {}".format(str(region)))
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "region_id": region.get("RegionId"),
                "name": region.get("LocalName"),
                "api_reference": region.get("RegionId"),
                "display_name": region.get("LocalName"),
                "aliases": [],
                "country_id": aliyun_region_coords.get(region.get("RegionId")).get("country_id"),
                "state": None,
                "city": aliyun_region_coords.get(region.get("RegionId")).get("city"),
                "address_line": None,
                "zip_code": None,
                "lon": aliyun_region_coords.get(region.get("RegionId")).get("lon"),
                "lat": aliyun_region_coords.get(region.get("RegionId")).get("lat"),
                "founding_year": None,
                "green_energy": None,
            }
        )
    return items


def inventory_zones(vendor):
    items =[]

    region_info_in_list = get_regions()
    for region in region_info_in_list.get("Regions").get("Region"):
        # a try block with a specific exception for timeout would be probably better, but why should we wait for the timeout
        if "cn-" in region.get("RegionId"):
            continue # chinese regions are not accessible from here
        else:
            tempclient = AcsClient(
                os.environ["ALIYUN_ACCESS_KEY"],
                os.environ["ALIYUN_SECRET"],
                region.get("RegionId")
            )
            
            zone_info_in_list = get_zones(tempcl=tempclient)
            for zone in zone_info_in_list.get("Zones").get("Zone"):  
                #print("Getting zone {} in region {}...".format(region.get("RegionId"), zone.get("ZoneId")))
                items.append({
                    "vendor_id": vendor.vendor_id,
                    "region_id": region.get("RegionId"),
                    "zone_id": zone.get("ZoneId"),
                    "name": zone.get("ZoneId"),
                    "api_reference": zone.get("ZoneId"),
                    "display_name": zone.get("ZoneId"),
                })

    return items

def inventory_servers(vendor):
    items = []
    instance_info_in_list = get_instance_types()
    for instancetype in instance_info_in_list.get("InstanceTypes").get("InstanceType"):
        cpu_arch_info = instancetype.get("CpuArchitecture").upper()
        if cpu_arch_info == "X86":
            set_cpu_arch = CpuArchitecture.X86_64
        elif cpu_arch_info == "ARM":
            set_cpu_arch = CpuArchitecture.ARM64
        else:
            set_cpu_arch = None   
        items.append(
            {
                "vendor_id": vendor.vendor_id,
                "server_id": instancetype.get("InstanceTypeId"),
                "name": instancetype.get("InstanceTypeId"),
                "api_reference": instancetype.get("InstanceTypeId"),
                "display_name": instancetype.get("InstanceTypeId"),
                "description": "{ifam}, {icat}".format(icat=instancetype.get("InstanceCategory"), ifam=instancetype.get("InstanceFamilyLevel")),
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
                "memory_amount": int((instancetype.get("MemorySize")*1024)),
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

# describeinstance region id paraméter, méásik régióból lekérdezni -- todo
# pr-nál todo comment, kitölteni amit lehet

def inventory_server_prices(vendor):
    # since the system treats pricing as a whole for the instance with every accessory, 
    # cloud disk type (cheapest HDD) is assumed for every instance type.
    items = []
    client = get_client()
    instance_info_in_list = get_instance_types()
    for instancetype in instance_info_in_list.get("InstanceTypes").get("InstanceType"):
        try:
            instance_info = get_instance_price(client, instancetype.get("InstanceTypeId"))
            print("Adding instance info - Region: {tcl}, instance type: {itype}".format(tcl=client.get_region_id(), itype=instancetype.get("InstanceTypeId")))

            items.append({
                "vendor_id": vendor.vendor_id,
                "region_id": client.get_region_id(),
                "zone_id": client.get_region_id()+"a",
                "server_id": instancetype.get("InstanceTypeId") ,
                "operating_system": "Linux",
                "allocation": Allocation.ONDEMAND,
                "unit": PriceUnit.HOUR,
                "price": instance_info.get("PriceInfo").get("Price").get("TradePrice"),
                "price_upfront": 0,
                "price_tiered": [],
                "currency": instance_info.get("PriceInfo").get("Price").get("Currency"),
            })  
        except ServerException as se:
            print(se)
            print("Failed to add instance info - Region: {tcl}, instance type: {itype}".format(tcl=client.get_region_id(), itype=instancetype.get("InstanceTypeId")))





    # for server in []:
    #     items.append({
    #         "vendor_id": ,
    #         "region_id": ,
    #         "zone_id": ,
    #         "server_id": ,
    #         "operating_system": ,
    #         "allocation": Allocation....,
    #         "unit": PriceUnit.HOUR,
    #         "price": ,
    #         "price_upfront": 0,
    #         "price_tiered": [],
    #         "currency": "USD",
    #     })
    return items


def inventory_server_prices_spot(vendor):

    return []


def inventory_storages(vendor):
    items = []

    # hardcoded, because API does not give back this information. MB/s converted to Mb/s
    # source: https://www.alibabacloud.com/help/en/ecs/user-guide/essds

    disk_info = [
        { "name": "cloud_essd-pl0",     "min_size": 1,    "max_size": 65536, "max_iop": 10000,    "max_tp":1440  , "info": "Enterprise SSD with Performance level 0."},
        { "name": "cloud_essd-pl1",     "min_size": 20,   "max_size": 65536, "max_iop": 50000,    "max_tp":2800  , "info": "Enterprise SSD with Performance level 1."},
        { "name": "cloud_essd-pl2",     "min_size": 461,  "max_size": 65536, "max_iop": 100000,   "max_tp":6000  , "info": "Enterprise SSD with Performance level 2."},
        { "name": "cloud_essd-pl3",     "min_size": 1261, "max_size": 65536, "max_iop": 1000000,  "max_tp":32000 , "info": "Enterprise SSD with Performance level 3."},
        { "name": "cloud_ssd",          "min_size": 20,   "max_size": 32768, "max_iop": 20000,    "max_tp":256   , "info": "Standard SSD."},
        { "name": "cloud_efficiency",   "min_size": 20,   "max_size": 32768, "max_iop": 3000,     "max_tp":80    , "info": "Ultra Disk, older generation."},
        { "name": "cloud",              "min_size": 5,    "max_size": 2000,  "max_iop": 300,      "max_tp":40    , "info": "Lowest cost HDD."}
    ]

    for disk in disk_info:
        items.append(
            {
                "storage_id": disk.get("name"),
                "vendor_id": vendor.vendor_id,
                "name": disk.get("name"),
                "description": disk.get("info"),
                "storage_type": StorageType.HDD if  disk.get("name") == 'cloud' else StorageType.SSD,
                "max_iops": disk.get("max_iop"),
                "max_throughput": disk.get("max_tp"),
                "min_size": disk.get("min_size"),
                "max_size": disk.get("max_size"),
            }
        )
    return items


def inventory_storage_prices(vendor):
    # --- NOTE: currently hardcoded all options, cycling through the possibilites, and catching exceptions for 
    #  unavailable disk-region combinations. a nicer implementation would be to get data from the bss service api.
    items = []
    tempclient = get_client()

    DEFAULT_INSTANCE_TYPE = "ecs.c6.large" # common instance, available in most regions. required for query.
    options_system_disk_category = ["cloud", "cloud_efficiency", "cloud_ssd", "ephemeral_ssd", "cloud_essd", "cloud_auto"]
    options_essd_disk_performance_level = ['PL0', 'PL1', 'PL2', 'PL3']

    # cycling through regions, so we can get region-based data
    region_info_in_list = get_regions()
    for region in region_info_in_list.get("Regions").get("Region"):
        # a try block with a specific exception for timeout would be probably better, but why should we wait for the timeout
        if "cn-" in region.get("RegionId"):
            continue # chinese regions are not accessible from here
        else:
            tempclient = AcsClient(
                os.environ["ALIYUN_ACCESS_KEY"],
                os.environ["ALIYUN_SECRET"],
                region.get("RegionId")
            )

        for disk in options_system_disk_category:
            request = DescribePriceRequest.DescribePriceRequest()
            request.set_PriceUnit("Hour")
            request.set_InstanceType(DEFAULT_INSTANCE_TYPE)
            request.set_DataDisk1Size(500)
            request.set_DataDisk1Category(disk)
            if disk == "cloud_essd":
                for pl in options_essd_disk_performance_level:
                    request.set_DataDisk1PerformanceLevel(pl)
                    try:
                        response = tempclient.do_action_with_exception(request)
                        respone_dict = (json.loads(response.decode("utf-8"))) 

                        for dti in respone_dict.get("PriceInfo").get("Price").get("DetailInfos").get("DetailInfo"):
                            if dti.get("Resource") == "systemDisk" or dti.get("Resource") == "dataDisk":
                                items.append(
                                    {
                                        "vendor_id": vendor.vendor_id,
                                        "region_id": tempclient.get_region_id() ,
                                        "storage_id": disk+"-"+pl,
                                        "unit": PriceUnit.GB_MONTH,
                                        "price": dti.get("TradePrice"),
                                        "currency": respone_dict.get("PriceInfo").get("Price").get("Currency"),
                                    }
                                )
                    except ServerException as se:
                        print(se)
                        print("tempclient: {tcl}, disk: {disk}, size: {size}, pl: {pl}".format(tcl=tempclient.get_region_id(), disk=disk, size=500, pl=pl))
            else:
                try:
                    response = tempclient.do_action_with_exception(request)
                    respone_dict = (json.loads(response.decode("utf-8"))) 
                    for dti in respone_dict.get("PriceInfo").get("Price").get("DetailInfos").get("DetailInfo"):
                        if dti.get("Resource") == "systemDisk" or dti.get("Resource") == "dataDisk":
                            items.append(
                                {
                                    "vendor_id": vendor.vendor_id,
                                    "region_id": tempclient.get_region_id() ,
                                    "storage_id": disk,
                                    "unit": PriceUnit.GB_MONTH,
                                    "price": dti.get("TradePrice"),
                                    "currency": respone_dict.get("PriceInfo").get("Price").get("Currency"),
                                }
                            )
                except ServerException as se:
                    print(se)
                    print("tempclient: {tcl}, disk: {disk}, size: {size}".format(tcl=tempclient.get_region_id(), disk=disk, size=500))

    return items


def inventory_traffic_prices(vendor):
    
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