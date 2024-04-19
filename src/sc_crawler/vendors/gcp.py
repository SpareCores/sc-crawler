from ..lookup import map_compliance_frameworks_to_vendor


# ##############################################################################
# Cached gcp client wrappers


# ##############################################################################
# Internal helpers


# ##############################################################################
# Public methods to fetch data


def inventory_compliance_frameworks(vendor):
    """Manual list of compliance frameworks known for GCP.

    Resources: <https://cloud.google.com/compliance?hl=en>"""
    return map_compliance_frameworks_to_vendor(
        vendor.vendor_id, ["hipaa", "soc2t2", "iso27001"]
    )


def inventory_datacenters(vendor):
    return []


def inventory_zones(vendor):
    return []


def inventory_servers(vendor):
    return []


def inventory_server_prices(vendor):
    return []


def inventory_server_prices_spot(vendor):
    return []


def inventory_storages(vendor):
    return []


def inventory_storage_prices(vendor):
    return []


def inventory_traffic_prices(vendor):
    return []


def inventory_ipv4_prices(vendor):
    return []
