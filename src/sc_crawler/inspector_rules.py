"""Rules for which servers and managed databases the Inspector runs its tasks on."""

from typing import TYPE_CHECKING, List

from .table_bases import DatabaseBase
from .table_fields import AcceleratorType, DatabaseHaLevel, DatabaseHaStrategy

if TYPE_CHECKING:
    from .tables import Database, Server


def block_reasons(
    resource: "Server | Database", tasks: str | List[str]
) -> dict[str, List[str]]:
    """Check in a deterministic way if the resource should run the given inspector task(s).

    Lists of inspector tasks defined at https://github.com/SpareCores/sc-inspector/blob/main/inspector/tasks.py

    A task doesn't run on a resource for any of these reasons:

    - All tasks:
        - Cloud credits or budget exhausted: Alibaba Cloud, AWS, Azure and GCP.

    - Managed databases:
        - Databases that can't be deployed on a single node.

    - Servers:
        - `bw_mem` and `membench`: a few servers with identified performance issues while running this task.
        - `nvidia_smi` and `nvbandwidth`: servers without GPUs, and a few AWS and GCP GPU server types that failed in the past.
        - Not enough memory: `membench` needs 0.9 GB; `compression_text`, `ffmpeg` and `llm` 1 GB; `vllm` and `pgbench_postgres_ro_durable` 2 GB; `geekbench` 2.1 GB.
        - `geekbench` and `passmark`: more than 32 vCPUs, as they don't scale beyond that.
        - `storage`: no bundled storage.
        - `stressnglongrun`: explicit allowlist for a few small AWS, GCP and Hetzner Cloud server types.

    Args:
        resource: The server or managed database.
        tasks: Name of an inspector task, or a list of them.

    Returns:
        The reasons per task, with an empty list for a task that can run.
    """
    # default to no block reasons for each task
    if isinstance(tasks, str):
        tasks = [tasks]
    results = {task: [] for task in tasks}
    for task in tasks:
        # override the overrides: although no credits, we still want to run these
        if task == "stressng_benchmarks":
            if (resource.vendor_id, resource.api_reference) in [
                ("aws", "c6a.large"),
                ("aws", "c6a.2xlarge"),
                ("aws", "c6g.xlarge"),
                ("aws", "m7a.xlarge"),
                ("aws", "c7a.32xlarge"),
                ("aws", "c6i.metal"),
            ]:
                continue

        # cloud credits either exhausted, pending, or abandoned
        if resource.vendor_id in ["alicloud", "aws", "azure", "gcp"]:
            results[task].append("Cloud credit/budget exhausted.")

        # databases checks: deny if 1-node layout is not supported
        if isinstance(resource, DatabaseBase):
            if (
                DatabaseHaLevel.NONE not in resource.ha
                or DatabaseHaStrategy.NONE not in resource.ha_strategy
            ):
                results[task].append("Database doesn't support single-node deployment.")
            # all the below rules apply to servers
            continue

        # explicit server exclusions
        if (
            task == "bw_mem"
            and (resource.vendor_id, resource.api_reference)
            in [
                ("ovh", "a10-180"),
                ("ovh", "l4-360"),
            ]
        ) or (
            task == "membench"
            and (resource.vendor_id, resource.api_reference) in [("ovh", "r3-128")]
        ):
            results[task].append(
                "We experienced performance issues while running this task on this server type."
            )
        if task in ["nvidia_smi", "nvbandwidth"]:
            if (
                resource.accelerator_count == 0
                or resource.accelerator_type == AcceleratorType.TPU
            ):
                results[task].append("No GPUs available.")
            # TODO these failed in the past, we should revisit if recent updates (e.g. newer drivers) fixed them
            if (resource.vendor_id, resource.api_reference) in [
                ("aws", "g3.4xlarge"),
                ("aws", "g3.8xlarge"),
                ("aws", "g3.16xlarge"),
                ("aws", "g4dn.metal"),
                ("aws", "p2.8xlarge"),
                ("aws", "p2.xlarge"),
                ("aws", "p4d.24xlarge"),
                ("aws", "g3s.xlarge"),
                ("gcp", "a2-megagpu-16g"),
            ]:
                results[task].append("GPUs not supported by this server type.")

        for memreq in [
            ("membench", 0.9),
            ("compression_text", 1.0),
            ("ffmpeg", 1.0),
            ("llm", 1.0),
            ("vllm", 2.0),
            ("geekbench", 2.1),
            ("pgbench_postgres_ro_durable", 2.0),
        ]:
            if task == memreq[0]:
                if resource.memory_amount < memreq[1] * 1024:
                    results[task].append(
                        f"Insufficient memory ({memreq[1]} GB minimum)."
                    )

        if task in ["geekbench", "passmark"]:
            if resource.vcpus > 32:
                results[task].append("Benchmark doesn't scale beyond 32 cores.")

        if task == "storage":
            if resource.storage_size == 0:
                results[task].append("No bundled storage available.")

        # runs for a full day, so limited to a very few SKUs
        if task == "stressnglongrun":
            if (resource.vendor_id, resource.api_reference) not in [
                ("aws", "t4g.medium"),
                ("aws", "c7g.large"),
                ("gcp", "e2-medium"),
                ("gcp", "c2d-highcpu-2"),
                ("hcloud", "cx21"),
                ("hcloud", "cx22"),
                ("hcloud", "cax11"),
                ("hcloud", "ccx13"),
            ]:
                results[task].append("Benchmark limited to a few SKUs.")

    return results
