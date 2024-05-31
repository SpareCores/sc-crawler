import json
from atexit import register
from functools import cache
from os import PathLike, path, remove
from re import sub
from shutil import rmtree
from tempfile import mkdtemp
from typing import List, TYPE_CHECKING
from zipfile import ZipFile

from requests import get

from .logger import logger

if TYPE_CHECKING:
    from .tables import Server


@cache
def inspector_data_path() -> str | PathLike:
    """Download current inspector data into a temp folder."""
    temp_dir = mkdtemp()
    register(rmtree, temp_dir)
    response = get(
        "https://github.com/SpareCores/sc-inspector-data/archive/refs/heads/main.zip"
    )
    zip_path = path.join(temp_dir, "downloaded.zip")
    with open(zip_path, "wb") as f:
        f.write(response.content)
    with ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(temp_dir)
    remove(zip_path)
    return path.join(temp_dir, "sc-inspector-data-main", "data")


def _server_ids(server: "Server") -> dict:
    return {"vendor_id": server.vendor_id, "server_id": server.server_id}


def _server_path(server: "Server") -> str | PathLike:
    return path.join(inspector_data_path(), server.vendor_id, server.api_reference)


def _server_framework_path(
    server: "Server", framework: str, relpath: str = None
) -> str | PathLike:
    path_parts = [_server_path(server), framework, relpath]
    path_parts = [path_part for path_part in path_parts if path_part is not None]
    return path.join(*path_parts)


def _server_framework_stdout_path(server: "Server", framework: str) -> str | PathLike:
    return _server_framework_path(server, framework, "stdout")


def _server_framework_stdout_from_json(server: "Server", framework: str) -> dict:
    with open(_server_framework_stdout_path(server, framework), "r") as fp:
        return json.load(fp)


def _server_framework_meta(server: "Server", framework: str) -> dict:
    with open(_server_framework_path(server, framework, "meta.json"), "r") as fp:
        return json.load(fp)


    return {"observed_at": _server_framework_meta(server, framework)["end"]}
def _observed_at(server: "Server", framework: str) -> dict:


def _benchmark_metafields(
    server: "Server", framework: str = None, benchmark_id: str = None
) -> dict:
    if benchmark_id is None:
        if framework is None:
            raise ValueError("At least framework or benchmark_id is to be provided.")
        benchmark_id = framework
    if framework is None:
        framework = benchmark_id.split(":")[0]
    return {
        **_server_ids(server),
        **_observed_at(server, framework),
        "benchmark_id": benchmark_id,
    }


def _log_cannot_load_benchmarks(server, benchmark_id, e, exc_info=False):
    logger.debug(
        "%s benchmark(s) not loaded for %s/%s: %s",
        benchmark_id,
        server.vendor_id,
        server.api_reference,
        e,
        stacklevel=2,
        exc_info=exc_info,
    )


def inspect_server_benchmarks(server: "Server") -> List[dict]:
    benchmarks = []

    framework = "bw_mem"
    try:
        with open(_server_framework_stdout_path(server, framework), "r") as lines:
            for line in lines:
                row = line.strip().split()
                benchmarks.append(
                    {
                        **_benchmark_metafields(server, framework=framework),
                        "config": {"what": row[0], "size": float(row[1])},
                        "score": float(row[2]),
                    }
                )
    except Exception as e:
        _log_cannot_load_benchmarks(server, framework, e)

    framework = "compression_text"
    try:
        algos = _server_framework_stdout_from_json(server, framework)
        for algo, levels in algos.items():
            for level, datas in levels.items():
                for data in datas:
                    config = {
                        "algo": algo,
                        "compression_level": None if level == "null" else int(level),
                        "threads": data["threads"],
                    }
                    if data.get("extra_args", {}).get("block_size"):
                        config["block_size"] = data["extra_args"]["block_size"]
                    for measurement in ["ratio", "compress", "decompress"]:
                        benchmarks.append(
                            {
                                **_benchmark_metafields(
                                    server,
                                    benchmark_id=":".join([framework, measurement]),
                                ),
                                "config": config,
                                "score": data[measurement],
                            }
                        )
    except Exception as e:
        _log_cannot_load_benchmarks(server, framework, e, True)

    framework = "geekbench"
    try:
        with open(_server_framework_path(server, framework, "results.json"), "r") as fp:
            scores = json.load(fp)
        geekbench_version = _server_framework_meta(server, framework)["version"]
        for cores, workloads in scores.items():
            for workload, values in workloads.items():
                workload_fields = {
                    "config": {
                        "geekbench_version": geekbench_version,
                        "cores": cores,
                    },
                    "score": values["score"],
                }
                if values.get("description"):
                    workload_fields["note"] = values["description"]
                benchmarks.append(
                    {
                        **_benchmark_metafields(
                            server,
                            benchmark_id=":".join(
                                [framework, sub(r"\W+", "_", workload.lower())]
                            ),
                        ),
                        **workload_fields,
                    }
                )
    except Exception as e:
        _log_cannot_load_benchmarks(server, framework, e, True)

    framework = "openssl"
    try:
        with open(_server_framework_path(server, framework, "parsed.json"), "r") as fp:
            workloads = json.load(fp)
        for workload in workloads:
            benchmarks.append(
                {
                    **_benchmark_metafields(server, framework=framework),
                    "config": {
                        "algo": workload["algo"],
                        "block_size": workload["block_size"],
                    },
                    "score": workload["speed"],
                }
            )
    except Exception as e:
        _log_cannot_load_benchmarks(server, framework, e, True)

    # TODO stress-ng

    return benchmarks
