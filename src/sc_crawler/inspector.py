import json
from atexit import register
from functools import cache
from os import PathLike, path, remove
from shutil import rmtree
from tempfile import mkdtemp
from typing import List
from zipfile import ZipFile

from requests import get

from .logger import logger
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


def _server_ids(server: Server) -> dict:
    return {"vendor_id": server.vendor_id, "server_id": server.server_id}


def _server_path(server: Server) -> str | PathLike:
    return path.join(inspector_data_path(), server.vendor_id, server.api_reference)


def _server_framework_path(server: Server, framework: str) -> str | PathLike:
    return path.join(_server_path(server), framework)


def _server_framework_stdout_path(server: Server, framework: str) -> str | PathLike:
    return path.join(_server_framework_path(server, framework), "stdout")


def _server_framework_meta_path(server: Server, framework: str) -> str | PathLike:
    return path.join(_server_framework_path(server, framework), "meta.json")


def _observed_at(server: Server, framework: str) -> dict:
    with open(_server_framework_meta_path(server, framework), "r") as meta_file:
        meta = json.load(meta_file)
    return {"observed_at": meta["end"]}


def _benchmark_metafields(
    server: Server, framework: str = None, benchmark_id: str = None
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


def _log_cannot_load_benchmarks(server, benchmark_id, e):
    logger.debug(
        "%s benchmark(s) not loaded for %s/%s: %s",
        benchmark_id,
        server.vendor_id,
        server.api_reference,
        e,
        stacklevel=2,
    )


def inspect_server_benchmarks(server: Server) -> List[dict]:
    benchmarks = []

    # memory bandwidth benchmarks
    benchmark_id = "bw_mem"
    try:
        with open(_server_framework_stdout_path(server, benchmark_id), "r") as lines:
            for line in lines:
                row = line.strip().split()
                benchmarks.append(
                    {
                        **_benchmark_metafields(server, benchmark_id),
                        "config": {"what": row[0], "size": float(row[1])},
                        "score": float(row[2]),
                    }
                )
    except Exception as e:
        _log_cannot_load_benchmarks(server, benchmark_id, e)

    return benchmarks
