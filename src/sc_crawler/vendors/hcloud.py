def inventory_compliance_frameworks(vendor):
    """Manual list of known compliance frameworks at Hetzner.

    Data collected from <https://www.hetzner.com/unternehmen/zertifizierung>."""
    ## TODO refactor to helper
    compliance_frameworks = ["iso27001"]
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
