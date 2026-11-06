from contextlib import ExitStack
from os import path
from unittest.mock import patch

import pytest

from sc_crawler.inspector import (
    _server_framework_meta,
    _server_framework_path,
    _standardize_gpu_count,
    inspect_update_server_dict,
)
from sc_crawler.table_bases import ServerBase
from sc_crawler.table_fields import CpuAllocation, CpuArchitecture, Status, StorageType

_INSPECTOR_LOOKUPS = (
    "_server_dmidecode_section",
    "_server_dmidecode_sections",
    "_server_lscpu",
    "_server_lshw",
    "_server_lstopo",
    "_server_lsblk",
    "_server_lsblk_discard",
    "_server_lsblk_topo",
    "_server_nvidiasmi",
    "_server_virtualization",
    "_server_stressngfull",
)


def _patch_missing_inspector_lookups(stack, **overrides):
    for name in _INSPECTOR_LOOKUPS:
        if name in overrides:
            stack.enter_context(
                patch(f"sc_crawler.inspector.{name}", return_value=overrides[name])
            )
        else:
            stack.enter_context(
                patch(
                    f"sc_crawler.inspector.{name}",
                    side_effect=FileNotFoundError(name),
                )
            )
    stack.enter_context(
        patch("sc_crawler.inspector._get_server_framework_run_ids", return_value=[])
    )


def test_standardize_gpu_count_from_alicloud_gpuspec():
    """AliCloud encodes fractional vGPUs in GPUSpec, e.g. "NVIDIA P4*1/4"."""
    assert _standardize_gpu_count("NVIDIA P4*1/4", 1) == 0.25
    assert _standardize_gpu_count("NVIDIA T4/8", 1) == 0.125
    assert _standardize_gpu_count("NVIDIA A10*1", 1) == 1
    # whole counts are returned as-is, so descriptions stay "8xV100"
    assert _standardize_gpu_count("NVIDIA V100", 8) == 8
    assert isinstance(_standardize_gpu_count("NVIDIA V100", 8), int)
    assert _standardize_gpu_count("", 0) == 0


def test_standardize_gpu_count_from_aws_gpu_memory():
    """AWS g6f / gr6f report no GPU count, only the L4 slice memory."""
    assert _standardize_gpu_count("L4", 0, 5722) == pytest.approx(0.25)
    assert _standardize_gpu_count("L4", 0, 22888) == pytest.approx(1)
    # other models without a count stay untouched
    assert _standardize_gpu_count("A100", 0, 40960) == 0


def test_standardize_gpu_count_from_gcp_description():
    """GCP machineTypes report count=1 for G4 vGPU slices, fraction is in description."""
    assert (
        _standardize_gpu_count(
            gpu_count=1,
            description="Graphics Optimized: 1/8 NVIDIA RTX PRO 6000 GPU, 6 vCPUs, 22GB RAM",
        )
        == 0.125
    )
    assert (
        _standardize_gpu_count(
            gpu_count=4,
            description="Accelerator Optimized: 4 NVIDIA GB300 GPU, 144 vCPUs, 960GB RAM",
        )
        == 4
    )
    # TPU machines and vendor descriptions without GPUs keep the API count
    assert (
        _standardize_gpu_count(
            gpu_count=1, description="24 vCPUs, 48 GB RAM, 1 Google TPUs"
        )
        == 1
    )
    assert _standardize_gpu_count(gpu_count=2, description="g2 family (8 vCPUs)") == 2


def _z4d_server():
    storage_size = round(24 * 3500 * 1024**3 / 1000**3)
    return {
        "vendor_id": "gcp",
        "server_id": "z4d-highmem-192-highlssd",
        "name": "z4d-highmem-192-highlssd",
        "api_reference": "z4d-highmem-192-highlssd",
        "display_name": "z4d-highmem-192-highlssd",
        "description": "Storage Optimized",
        "vcpus": 192,
        "cpu_allocation": CpuAllocation.DEDICATED,
        "cpu_architecture": CpuArchitecture.X86_64,
        "memory_amount": 1548288,
        "storage_size": storage_size,
        "storage_type": StorageType.NVME_SSD,
        "storages": [{"size": storage_size, "storage_type": StorageType.NVME_SSD}],
    }


def test_gcp_keeps_api_storage_when_inspector_has_no_sample():
    expected = _z4d_server()
    with ExitStack() as stack:
        _patch_missing_inspector_lookups(stack)
        updated = inspect_update_server_dict(_z4d_server())

    assert updated["memory_amount"] == expected["memory_amount"]
    assert updated["storage_size"] == expected["storage_size"]
    assert updated["storage_type"] == expected["storage_type"]
    assert updated["storages"] == expected["storages"]


def test_gcp_inspector_lsblk_still_overrides_api_storage():
    partition_gb = (3500 * 1024**3) // 1000**3
    lsblk = {
        "blockdevices": [
            {"name": "nvme0n1", "size": 10 * 1000**3},
            {"name": "nvme1n1", "size": 3500 * 1024**3},
        ]
    }
    with ExitStack() as stack:
        _patch_missing_inspector_lookups(stack, _server_lsblk=lsblk)
        updated = inspect_update_server_dict(_z4d_server())

    assert updated["storage_size"] == partition_gb
    assert updated["storage_type"] == StorageType.NVME_SSD
    assert len(updated["storages"]) == 1
    assert updated["storages"][0].size == partition_gb


def test_gcp_inspector_lsblk_skips_boot_persistent_disk_by_model():
    # the boot Persistent Disk is not always nvme0, e.g. on a3-highgpu-8g
    partition_gb = (375 * 1024**3) // 1000**3
    lsblk = {
        "blockdevices": [
            {"name": "nvme0n1", "size": 375 * 1024**3, "model": "nvme_card8"},
            {"name": "nvme1n1", "size": 128 * 1024**3, "model": "nvme_card-pd"},
            {"name": "nvme2n1", "size": 375 * 1024**3, "model": "nvme_card0"},
        ]
    }
    with ExitStack() as stack:
        _patch_missing_inspector_lookups(stack, _server_lsblk=lsblk)
        updated = inspect_update_server_dict(_z4d_server())

    assert updated["storage_size"] == 2 * partition_gb
    assert [disk.size for disk in updated["storages"]] == [partition_gb] * 2


def test_missing_nvidia_smi_does_not_mark_server_as_gpu():
    with ExitStack() as stack:
        _patch_missing_inspector_lookups(stack)
        updated = inspect_update_server_dict(_z4d_server())

    assert updated.get("accelerator_type") is None


def _variant_server(tmp_path, monkeypatch, layout):
    """Create an inspector data tree for one server: {relpath: content}."""
    monkeypatch.setattr(
        "sc_crawler.inspector.inspector_data_path",
        lambda dir_name="data": str(tmp_path / dir_name),
    )
    base = tmp_path / "data" / "azure" / "Standard_D2ds_v5"
    for relpath, content in layout.items():
        file = base / relpath
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
    return ServerBase(
        vendor_id="azure",
        server_id="Standard_D2ds_v5",
        name="Standard_D2ds_v5",
        api_reference="Standard_D2ds_v5",
        display_name="Standard_D2ds_v5",
        description="test",
        vcpus=2,
        memory_amount=8192,
        storage_size=0,
        status=Status.ACTIVE,
    )


def test_server_framework_path_prefers_variant_0(tmp_path, monkeypatch):
    server = _variant_server(
        tmp_path,
        monkeypatch,
        {
            "0/lscpu/stdout": "v0",
            "1/lscpu/stdout": "v1",
            "schedule/lscpu/meta.json": "{}",
        },
    )
    with open(_server_framework_path(server, "lscpu", "stdout")) as fp:
        assert fp.read() == "v0"


def test_server_framework_path_falls_back_to_other_variant(tmp_path, monkeypatch):
    """A benchmark that only ran on a newer hardware variant is still found."""
    server = _variant_server(
        tmp_path,
        monkeypatch,
        {
            "0/lscpu/stdout": "v0",
            "2/pgbench_postgres_ro_durable/stdout": "v2",
            "10/pgbench_postgres_ro_durable/stdout": "v10",
            "1/pgbench_postgres_ro_durable/stdout": "v1",
            "1/pgbench_postgres_ro_durable/meta.json": '{"exit_code": 0}',
            "schedule/pgbench_postgres_ro_durable/meta.json": '{"exit_code": 1}',
        },
    )
    framework = "pgbench_postgres_ro_durable"
    with open(_server_framework_path(server, framework, "stdout")) as fp:
        assert fp.read() == "v1"
    assert _server_framework_meta(server, framework) == {"exit_code": 0}


def test_server_framework_path_missing_framework(tmp_path, monkeypatch):
    """A framework no variant has resolves to a missing path under variant 0."""
    server = _variant_server(tmp_path, monkeypatch, {"1/lscpu/stdout": "v1"})
    missing = _server_framework_path(server, "geekbench", "stdout")
    assert not path.exists(missing)
    assert path.join("Standard_D2ds_v5", "0", "geekbench", "stdout") in str(missing)
    with pytest.raises(FileNotFoundError):
        _server_framework_meta(server, "geekbench")


def test_server_framework_path_skips_failed_or_unfinished_runs(tmp_path, monkeypatch):
    """An aborted run on one variant doesn't hide a successful run on another."""
    server = _variant_server(
        tmp_path,
        monkeypatch,
        {
            "0/pgbench_postgres_ro_durable/meta.json": '{"exit_code": 1}',
            "0/pgbench_postgres_ro_durable/stdout": "v0",
            "1/pgbench_postgres_ro_durable/meta.json": '{"exit_code": null}',
            "2/pgbench_postgres_ro_durable/meta.json": '{"exit_code": 0}',
            "2/pgbench_postgres_ro_durable/stdout": "v2",
        },
    )
    framework = "pgbench_postgres_ro_durable"
    with open(_server_framework_path(server, framework, "stdout")) as fp:
        assert fp.read() == "v2"
    assert _server_framework_meta(server, framework) == {"exit_code": 0}


def test_server_framework_path_keeps_failed_run_without_alternative(
    tmp_path, monkeypatch
):
    server = _variant_server(
        tmp_path,
        monkeypatch,
        {
            "1/geekbench/meta.json": '{"exit_code": 1}',
            "2/geekbench/meta.json": '{"exit_code": 2}',
        },
    )
    assert _server_framework_meta(server, "geekbench") == {"exit_code": 1}
