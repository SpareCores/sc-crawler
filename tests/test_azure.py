import pytest

from sc_crawler.table_fields import AcceleratorType
from sc_crawler.vendors._azure import _gpu_spec, _standardize_server


@pytest.mark.parametrize(
    "name,fpgas", [("Standard_NP10s", 1), ("Standard_NP20s", 2), ("Standard_NP40s", 4)]
)
def test_np_series_fpgas(name, fpgas):
    """NP-series FPGA count comes from the API, model and memory from the table."""
    assert _gpu_spec(name, str(fpgas)) == (fpgas, "Alveo U250", 64 * 1024)


def test_np_series_stored_as_fpga():
    """NP-series servers are stored with the FPGA accelerator type."""
    capabilities = {
        "CpuArchitectureType": "x64",
        "vCPUs": "20",
        "vCPUsAvailable": "20",
        "MemoryGB": "424",
        "GPUs": "2",
    }
    server = {
        "name": "Standard_NP20s",
        "family": "standardNPSFamily",
        "capabilities": [{"name": k, "value": v} for k, v in capabilities.items()],
    }
    row = _standardize_server(server, type("Vendor", (), {"vendor_id": "azure"})())
    assert row["accelerator_type"] == AcceleratorType.FPGA
    assert row["accelerator_count"] == 2
    assert row["accelerator_memory_total"] == 2 * 64 * 1024
