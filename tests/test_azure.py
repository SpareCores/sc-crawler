from types import SimpleNamespace

from sc_crawler.vendors._azure import _standardize_server


def test_family_strips_trailing_xl():
    server = {
        "name": "Standard_NC24lds_xl_RTXPRO6000BSE_v6",
        "family": "standardNCdsRTXPRO6000BSEv6XLFamily",
        "capabilities": [
            {"name": "CpuArchitectureType", "value": "x64"},
            {"name": "vCPUs", "value": "24"},
            {"name": "vCPUsAvailable", "value": "24"},
            {"name": "MemoryGB", "value": "72"},
        ],
    }
    result = _standardize_server(server, SimpleNamespace(vendor_id="azure"))
    assert result["family"] == "NCdsRTXPRO6000BSEv6"
