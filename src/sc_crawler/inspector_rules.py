"""Rules for which servers and managed databases the Inspector runs its tasks on."""

from typing import TYPE_CHECKING, List

from .table_bases import DatabaseBase
from .table_fields import AcceleratorType, DatabaseHaLevel, DatabaseHaStrategy

if TYPE_CHECKING:
    from .tables import Database, Server

# task                              n         min        mean      median         p90         p99         max
# -----------------------------------------------------------------------------------------------------------
# vllm                           1331    15m00.1s  1h03m03.1s  1h05m47.8s  1h30m43.3s  1h53m58.0s  2h23m06.4s
# llm                            3532     4m35.8s    30m58.0s    33m05.8s    41m38.5s    49m55.5s  1h29m01.4s
# pgbench_postgres_ro_durable     513    13m19.8s    24m25.6s    25m31.3s    25m50.0s    26m34.5s    27m23.9s
# stressng_benchmarks            2176     6m59.3s    14m44.2s    14m43.4s    15m04.3s    25m03.6s  1h05m35.0s
# geekbench                      3349        7.0s    13m50.2s     5m52.6s    10m22.3s  3h31m53.9s  6h09m37.1s
# static_web                     3606    11m36.1s    12m04.0s    11m49.3s    12m09.3s    18m59.4s    36m39.3s
# compression_text               3585     2m34.8s    11m28.3s    10m59.7s    18m59.6s    29m40.7s  1h47m56.5s
# ffmpeg                          361     2m47.5s     9m16.4s     9m25.9s    12m19.1s    14m23.3s    17m16.9s
# bw_mem                         3608       19.3s     5m45.4s     3m58.3s    13m16.6s    23m41.2s  1h31m04.2s
# openssl                        3618     3m19.6s     4m12.3s     3m47.4s     4m13.8s    16m14.8s  1h14m23.5s
# nvbandwidth                     170       21.5s     3m32.0s     2m22.9s     8m34.7s    18m13.3s    24m55.7s
# membench                       2206       35.5s     3m16.4s     2m24.4s     5m49.6s    15m17.2s    36m59.4s
# stressngfull                   3620       11.5s     3m05.0s     2m51.0s     5m40.3s     7m42.9s    49m32.4s
# passmark                       3598     1m09.1s     3m00.0s     2m53.8s     3m13.0s     7m00.8s    32m09.4s
# redis                          3602     1m09.1s     1m26.3s     1m17.3s     1m28.7s     3m32.2s    39m14.6s
# lstopo                         2258        1.5s       29.8s       12.9s       23.2s    12m02.5s    28m46.4s
# lshw                           3627        1.7s       24.7s       14.0s       25.8s     7m05.0s    28m46.2s
# lscpu                          3628        1.5s       24.4s       13.8s       25.5s     7m04.0s    28m46.4s
# stressng                       1606       21.0s       24.1s       23.6s       27.3s       31.8s       48.5s
# stressngsinglecore             1607       20.4s       21.1s       20.8s       21.8s       24.6s       38.2s
# virtualization                 3614        1.1s       19.7s       13.0s       22.6s     2m01.4s    28m46.2s
# lsblk                          2252        0.6s       19.0s        6.3s       15.0s     8m30.9s    46m55.5s
# dmidecode                      3577        1.0s       17.9s       10.3s       22.6s     2m20.9s    28m46.4s
# nvidia_smi                      176        2.4s       13.5s       13.7s       20.3s       30.9s     2m13.7s
# lsblk_discard                  2256        0.5s        4.7s        2.0s       12.7s       33.9s     4m56.0s
# lsblk_topo                     2255        0.5s        4.7s        2.1s       12.5s       33.7s     5m12.0s
# timing                         1699        0.0s        0.0s        0.0s        0.0s        0.0s        0.1s
_CHEAP_TASKS = [
    "geekbench",
    "openssl",
    "nvbandwidth",
    "membench",
    "stressngfull",
    "passmark",
    "redis",
    "lstopo",
    "lshw",
    "lscpu",
    "stressng",
    "stressngsinglecore",
    "virtualization",
    "lsblk",
    "dmidecode",
    "nvidia_smi",
    "lsblk_discard",
    "lsblk_topo",
]

_AZURE_UNSUPPORTED_DATABASE_FAMILIES = [
    # Azure PostgreSQL flexible server supports confidential computing only on the
    # Dcadsv5 and Ecadsv5 series, see
    # https://learn.microsoft.com/en-us/azure/postgresql/security/security-confidential-computing
    # These other confidential families are listed by our ingest (billing meters),
    # but are not actually offered by the vendor (found by the vendor audit, see audit/triage.yaml).
    "DCasv5",
    "ECasv5",
    "DCadsv6",
    "ECadsv6",
    "DCesv6",
    "ECesv6",
    # Not listed among the compute sizes of Azure PostgreSQL flexible server, see
    # https://learn.microsoft.com/en-us/azure/postgresql/compute-storage/concepts-compute
    # e.g. for v6, only the series with local disk (Ddsv6, Dadsv6, Edsv6, Eadsv6) are
    # supported. Likely listed by our ingest from billing meters as well, but not yet
    # verified in the Azure portal (found by the vendor audit, see audit/triage.yaml).
    "Dsv6",
    "Dasv6",
    "Esv6",
    "Easv6",
    "Ebdsv5",
    "Mdsv2",
]


def has_related_database(server: "Server") -> bool:
    """Check if the server is the underlying server of any Database of the same Vendor.

    Args:
        server: The server to look up in the `server_id` of the Vendor's Databases.

    Returns:
        True if at least one Database of the Vendor references the server.
    """
    return any(
        database.server_id == server.server_id for database in server.vendor.databases
    )


def is_credit_exempt(resource: "Server | Database", task: str) -> bool:
    """Check if the task should run on the resource despite exhausted cloud credits.

    Args:
        resource: The server or managed database.
        task: Name of an inspector task.

    Returns:
        True if the cloud credit block reason doesn't apply.
    """
    if resource.vendor_id == "azure" and resource.memory_amount < 1024**2:
        # need full DBaaS coverage at Azure for analysis (at least below 1TB RAM)
        if isinstance(resource, DatabaseBase):
            return True
        if task in [
            *_CHEAP_TASKS,
            "pgbench_postgres_ro_durable",
        ] and has_related_database(resource):
            return True
    if task == "stressng_benchmarks":
        # www blogpost citing data collected manually in 2024 that we need to repro
        if (resource.vendor_id, resource.api_reference) in [
            ("aws", "c6a.large"),
            ("aws", "c6a.2xlarge"),
            ("aws", "c6g.xlarge"),
            ("aws", "m7a.xlarge"),
            ("aws", "c7a.32xlarge"),
            ("aws", "c6i.metal"),
        ]:
            return True
    # we need lstopo for KCD Budapest 2026 talk
    if (resource.vendor_id, resource.api_reference) in [
        ("aws", "m8azn.metal-12xl")
    ] and task in _CHEAP_TASKS:
        return True
    return False


def block_reasons(
    resource: "Server | Database", tasks: str | List[str]
) -> dict[str, List[str]]:
    """Check in a deterministic way if the resource should run the given inspector task(s).

    Lists of inspector tasks defined at https://github.com/SpareCores/sc-inspector/blob/main/inspector/tasks.py

    A task doesn't run on a resource for any of these reasons:

    - All tasks:
        - Cloud credits or budget exhausted: Alibaba Cloud, AWS, Azure and GCP,
          except for a few explicitly exempted resources and tasks (see
          `is_credit_exempt`).

    - Managed databases:
        - Databases that can't be deployed on a single node.
        - Azure PostgreSQL SKUs that are not confirmed to be offered by the vendor.

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
        # cloud credits either exhausted, pending, or abandoned
        if resource.vendor_id in [
            "alicloud",
            "aws",
            "azure",
            "gcp",
        ] and not is_credit_exempt(resource, task):
            results[task].append("Cloud credit/budget exhausted.")

        # databases checks: deny if 1-node layout is not supported
        if isinstance(resource, DatabaseBase):
            if (
                DatabaseHaLevel.NONE not in resource.ha
                or DatabaseHaStrategy.NONE not in resource.ha_strategy
            ):
                results[task].append("Database doesn't support single-node deployment.")
            if (
                resource.vendor_id == "azure"
                and resource.family in _AZURE_UNSUPPORTED_DATABASE_FAMILIES
            ):
                results[task].append("Database SKU not offered by the vendor.")
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
