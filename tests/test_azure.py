import pytest

from sc_crawler.table_fields import AcceleratorType
from sc_crawler.vendors._azure import _parse_server_name, _standardize_server


@pytest.mark.parametrize(
    "name,fpgas", [("Standard_NP10s", 1), ("Standard_NP20s", 2), ("Standard_NP40s", 4)]
)
def test_np_series_fpgas(name, fpgas):
    family, _, count, model, memory = _parse_server_name(name)
    assert family == "NP"
    assert count == fpgas
    assert model == "Alveo U250"
    assert memory == 61035


def test_np_series_stored_as_fpga():
    capabilities = {
        "CpuArchitectureType": "x64",
        "vCPUs": "20",
        "vCPUsAvailable": "20",
        "MemoryGB": "424",
    }
    server = {
        "name": "Standard_NP20s",
        "family": "standardNPSFamily",
        "capabilities": [{"name": k, "value": v} for k, v in capabilities.items()],
    }
    row = _standardize_server(server, type("Vendor", (), {"vendor_id": "azure"})())
    assert row["accelerator_type"] == AcceleratorType.FPGA
    assert row["accelerator_count"] == 2
    assert row["accelerator_memory_total"] == 2 * 61035
