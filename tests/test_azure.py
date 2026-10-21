from types import SimpleNamespace

import pytest

from sc_crawler.vendors._azure import _standardize_server, _vm_family_category


@pytest.mark.parametrize(
    ("server_name", "family"),
    [
        ("Standard_D2s_v3", "General Purpose"),
        ("Standard_DC16as_v5", "General Purpose"),
        ("Standard_DS3_v2", "General Purpose"),
        ("Standard_B2ms", "General Purpose"),
        ("Standard_A4_v2", "General Purpose"),
        # no documentation lists A8-A11 other than the (general purpose) A family
        ("Standard_A8", "General Purpose"),
        ("Standard_F16s_v2", "Compute Optimized"),
        ("Standard_FX12mds", "Compute Optimized"),
        ("Standard_E32as_v6", "Memory Optimized"),
        ("Standard_EC64es_v6", "Memory Optimized"),
        ("Standard_M128s", "Memory Optimized"),
        # previous generation memory optimized sizes
        ("Standard_G1", "Memory Optimized"),
        ("Standard_GS5-16", "Memory Optimized"),
        # D11-D15 and DS11-DS15 are memory optimized, other D sizes are not
        ("Standard_D11", "Memory Optimized"),
        ("Standard_D15_v2", "Memory Optimized"),
        ("Standard_DS11-1_v2", "Memory Optimized"),
        ("Standard_DS14_v2", "Memory Optimized"),
        ("Standard_D16_v3", "General Purpose"),
        ("Standard_D1", "General Purpose"),
        ("Standard_L8s_v3", "Storage Optimized"),
        ("Standard_NC24ads_A100_v4", "GPU Accelerated"),
        ("Standard_NCC40ads_H100_v5", "GPU Accelerated"),
        ("Standard_ND96isr_H100_v5", "GPU Accelerated"),
        ("Standard_NV36ads_A10_v5", "GPU Accelerated"),
        ("Standard_NP10s", "FPGA Accelerated"),
        ("Standard_HB120rs_v3", "High Performance Compute"),
        # retired H-series
        ("Standard_H16r", "High Performance Compute"),
        # not documented by Microsoft, and unknown families are not guessed
        ("Standard_PB6s", None),
        ("Standard_ZZ4s_v1", None),
    ],
)
def test_azure_vm_family_category(server_name, family):
    assert _vm_family_category(server_name) == family


def test_azure_standardize_server_family_and_series():
    server = {
        "name": "Standard_NC4as_T4_v3",
        # the SKU family has spaces around the accelerator for some SKUs
        "family": "standard NCASv3_T4 Family",
        "capabilities": [
            {"name": "CpuArchitectureType", "value": "x64"},
            {"name": "vCPUs", "value": "4"},
            {"name": "vCPUsAvailable", "value": "4"},
            {"name": "MemoryGB", "value": "28"},
        ],
    }
    row = _standardize_server(server, SimpleNamespace(vendor_id="azure"))
    assert row["family"] == "GPU Accelerated"
    assert row["series"] == "NCASv3_T4"
