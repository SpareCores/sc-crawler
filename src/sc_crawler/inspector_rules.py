from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .tables import Server


def block_reasons(server: "Server", tasks: str | List[str]):
    """Check in a deterministic way if the server should run the given inspector task(s).

    Lists of inspector tasks defined at https://github.com/SpareCores/sc-inspector/blob/main/inspector/tasks.py
    """
    # default to no block reasons for each task
    if isinstance(tasks, str):
        tasks = [tasks]
    results = {task: [] for task in tasks}
    for task in tasks:
        # cloud credit requests either pending or abandoned
        if server.vendor_id in ["alicloud", "aws", "azure", "gcp"]:
            results[task].append("Cloud credit/budget exhausted.")

        if task in ["nvidia_smi", "nvbandwidth"]:
            if server.gpu_count == 0:
                results[task].append("No GPUs available.")
            # TODO these failed in the past, we should revisit if recent updates (e.g. newer drivers) fixed them
            if (server.vendor_id, server.api_reference) in [
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
                if server.memory_amount < memreq[1] * 1024:
                    results[task].append(
                        f"Insufficient memory ({memreq[1]} GB minimum)."
                    )

        if task in ["geekbench", "passmark"]:
            if server.vcpus > 32:
                results[task].append("Benchmark doesn't scale beyond 32 cores.")

        if task == "storage":
            if server.storage_size == 0:
                results[task].append("No bundled storage available.")

        # runs for a full day, so limited to a very few SKUs
        if task == "stressnglongrun":
            if (server.vendor_id, server.api_reference) not in [
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
