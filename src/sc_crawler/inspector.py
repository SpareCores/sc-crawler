import json
from atexit import register
from functools import cache
from os import PathLike, path, remove
from shutil import rmtree
from tempfile import mkdtemp
from typing import List
from zipfile import ZipFile

from requests import get

from ..logger import logger
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


def inspect_server_benchmarks(server: Server) -> List[dict]:
    benchmarks = []
    server_path = path.join(
        inspector_data_path(), server.vendor_id, server.api_reference
    )

    # memory bandwidth benchmarks
    try:
        with open(path.join(server_path, "bw_mem", "meta.json"), "r") as meta_file:
            meta = json.load(meta_file)
        with open(path.join(server_path, "bw_mem", "stdout"), "r") as lines:
            for line in lines:
                row = line.strip().split()
                benchmarks.append(
                    {
                        "vendor_id": server.vendor_id,
                        "server_id": server.server_id,
                        "benchmark_id": "bw_mem",
                        "config": {"what": row[0], "size": float(row[1])},
                        "score": float(row[2]),
                        "observed_at": meta["end"],
                    }
                )
    except Exception as e:
        logger.debug(
            "Memory bandwidth benchmarks not loaded for %s/%s: %s",
            server.vendor_id,
            server.api_reference,
            e,
            exc_info=True,
        )

    return benchmarks
