import json
import xml.etree.ElementTree as xmltree
from atexit import register
from functools import cache
from os import PathLike, path, remove
from re import compile, sub
from shutil import rmtree
from statistics import mode
from tempfile import mkdtemp
from typing import TYPE_CHECKING, List
from zipfile import ZipFile

from requests import get

from .logger import logger
from .table_bases import ServerBase
from .table_fields import DdrGeneration

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


def _server_framework_stderr_path(server: "Server", framework: str) -> str | PathLike:
    return _server_framework_path(server, framework, "stderr")


def _server_framework_stdout_from_json(server: "Server", framework: str) -> dict:
    with open(_server_framework_stdout_path(server, framework), "r") as fp:
        return json.load(fp)


def _server_framework_meta(server: "Server", framework: str) -> dict:
    with open(_server_framework_path(server, framework, "meta.json"), "r") as fp:
        return json.load(fp)


def _server_lscpu(server: "Server") -> dict:
    with open(_server_framework_path(server, "lscpu", "stdout"), "r") as fp:
        return json.load(fp)["lscpu"]


def _listsearch(items: List, key: str, value: str):
    return next((item for item in items if item[key] == value))


def _server_lscpu_field(server: "Server", field: str) -> str:
    return _listsearch(_server_lscpu(server), "field", field)["data"]


def _server_dmidecode(server: "Server") -> dict:
    with open(_server_framework_path(server, "dmidecode", "parsed.json"), "r") as fp:
        return json.load(fp)


def _server_dmidecode_section(server: "Server", section: str) -> dict:
    return _listsearch(_server_dmidecode(server), "name", section)["props"]


def _server_nvidiasmi(server: "Server") -> dict:
    return xmltree.parse(_server_framework_path(server, "nvidia_smi", "stdout"))


def _observed_at(server: "Server", framework: str) -> dict:
    ts = _server_framework_meta(server, framework)["end"]
    assert ts is not None
    return {"observed_at": ts}


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


def _extract_line_from_file(file_path: str | PathLike, pattern: str) -> str:
    """Find the first line of a text file matching the regular expression."""
    regex = compile(pattern)
    with open(file_path, "r") as lines:
        for line in lines:
            if regex.search(line):
                return line.strip()
    return None


def _log_cannot_load_benchmarks(server: "Server", benchmark_id, e, exc_info=False):
    logger.debug(
        "%s benchmark(s) not loaded for %s/%s: %s",
        benchmark_id,
        server.vendor_id,
        server.api_reference,
        e,
        stacklevel=2,
        exc_info=exc_info,
    )


def _log_cannot_update_server(server: "Server", key, e, exc_info=False):
    logger.debug(
        "Cannot update %s loaded for %s/%s: %s",
        key,
        server.vendor_id,
        server.api_reference,
        e,
        stacklevel=2,
        exc_info=exc_info,
    )


def inspect_server_benchmarks(server: "Server") -> List[dict]:
    """Generate a list of BenchmarkScore-like dicts for the Server."""
    benchmarks = []

    framework = "bogomips"
    try:
        benchmarks.append(
            {
                **_benchmark_metafields(
                    server, framework="lscpu", benchmark_id=framework
                ),
                "score": float(_server_lscpu_field(server, "BogoMIPS:")),
            }
        )
    except Exception as e:
        _log_cannot_load_benchmarks(server, framework, e)

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
                                "score": float(data[measurement]),
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
                    "config": {"cores": cores, "framework_version": geekbench_version},
                    "score": float(values["score"]),
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
        openssl_version = _server_framework_meta(server, framework)["version"]
        for workload in workloads:
            benchmarks.append(
                {
                    **_benchmark_metafields(server, framework=framework),
                    "config": {
                        "algo": workload["algo"],
                        "block_size": workload["block_size"],
                        "framework_version": openssl_version,
                    },
                    "score": float(workload["speed"]),
                }
            )
    except Exception as e:
        _log_cannot_load_benchmarks(server, framework, e, True)

    framework = "stress_ng"
    try:
        for cores_path in ["stressng", "stressngsinglecore"]:
            stressng_version = _server_framework_meta(server, cores_path)["version"]
            line = _extract_line_from_file(
                _server_framework_stderr_path(server, cores_path),
                "bogo-ops-per-second-real-time",
            )
            benchmarks.append(
                {
                    **_benchmark_metafields(
                        server,
                        framework=cores_path,
                        benchmark_id=":".join([framework, "cpu_all"]),
                    ),
                    "config": {
                        "cores": 1 if cores_path == "stressng" else server.vcpus,
                        "framework_version": stressng_version,
                    },
                    "score": float(line.split(": ")[1]),
                }
            )
    except Exception as e:
        _log_cannot_load_benchmarks(server, framework, e, True)

    return benchmarks


def _standardize_manufacturer(manufacturer):
    if manufacturer == "Advanced Micro Devices, Inc.":
        return "AMD"
    if manufacturer == "Intel(R) Corporation":
        return "Intel"
    if manufacturer in ["NVIDIA", "Tesla"]:
        return "Nvidia"
    return manufacturer


def _standardize_cpu_model(model):
    if model == "Not Specified":
        return None
    for prefix in ["Intel(R) Xeon(R) Platinum "]:
        if model.startswith(prefix):
            model = model[len(prefix) :].lstrip()
    # drop trailing "CPU @ 2.50GHz"
    model = sub(r" CPU @ \d+\.\d+GHz$", "", model)
    return model


def _l123_cache(lscpu: dict, level: int):
    if level == 1:
        l1i = _listsearch(lscpu, "field", "L1i cache:")["data"].split(" ")[0]
        l1d = _listsearch(lscpu, "field", "L1d cache:")["data"].split(" ")[0]
        return int(l1i) + int(l1d)
    elif level == 2:
        return int(_listsearch(lscpu, "field", "L2 cache:")["data"].split(" ")[0])
    elif level == 3:
        return int(_listsearch(lscpu, "field", "L3 cache:")["data"].split(" ")[0])
    else:
        raise ValueError("Not known cache level.")


def _dropna(text: str) -> str:
    if text in ["N/A"]:
        return None
    return text


def _gpu_details(gpu: xmltree.Element) -> dict:
    res = {}
    res["manufacturer"] = _standardize_manufacturer(gpu.find("product_brand").text)
    res["family"] = gpu.find("product_architecture").text
    res["model"] = gpu.find("product_name").text
    memstring = gpu.find("fb_memory_usage").find("total").text
    # TODO move computer_readable from sc-inspector to here or sc-helpers?
    res["memory"] = int(memstring[:-4])
    res["firmware_version"] = _dropna(gpu.find("gsp_firmware_version").text)
    res["bios_version"] = _dropna(gpu.find("vbios_version").text)
    for clock in ["graphics_clock", "sm_clock", "mem_clock", "video_clock"]:
        clockstring = gpu.find("max_clocks").find(clock).text
        res[clock] = int(clockstring[:-4])
    return res


def _gpus_details(gpus: List[xmltree.Element]) -> List[dict]:
    return [_gpu_details(gpu) for gpu in gpus]


def _gpu_most_common(gpus: List[dict], field: str) -> str:
    return mode([gpu[field] for gpu in gpus])


def inspect_update_server_dict(server: dict) -> dict:
    """Update a Server-like dict based on inspector data."""
    server_obj = ServerBase.validate(server)

    lookups = {
        "dmidecode_cpu": lambda: _server_dmidecode_section(
            server_obj, "Processor Information"
        ),
        "dmidecode_memory": lambda: _server_dmidecode_section(
            server_obj, "Memory Device"
        ),
        "lscpu": lambda: _server_lscpu(server_obj),
        "nvidiasmi": lambda: _server_nvidiasmi(server_obj),
        "gpu": lambda: lookups["nvidiasmi"].find("gpu"),
        "gpus": lambda: lookups["nvidiasmi"].findall("gpu"),
    }
    for k, f in lookups.items():
        try:
            lookups[k] = f()
        except Exception as e:
            lookups[k] = Exception(str(e))

    mappings = {
        "cpu_cores": lambda: lookups["dmidecode_cpu"]["Core Count"],
        # convert to Ghz
        "cpu_speed": lambda: lookups["dmidecode_cpu"]["Max Speed"] / 1e9,
        "cpu_manufacturer": lambda: _standardize_manufacturer(
            lookups["dmidecode_cpu"]["Manufacturer"]
        ),
        "cpu_family": lambda: lookups["dmidecode_cpu"]["Family"],
        "cpu_model": lambda: _standardize_cpu_model(
            lookups["dmidecode_cpu"]["Version"]
        ),
        "cpu_l1_cache": lambda: _l123_cache(lookups["lscpu"], 1),
        "cpu_l2_cache": lambda: _l123_cache(lookups["lscpu"], 2),
        "cpu_l3_cache": lambda: _l123_cache(lookups["lscpu"], 3),
        "cpu_flags": lambda: _listsearch(lookups["lscpu"], "field", "Flags:")[
            "data"
        ].split(" "),
        "memory_generation": lambda: DdrGeneration[lookups["dmidecode_memory"]["Type"]],
        # convert to Mhz
        "memory_speed": lambda: int(lookups["dmidecode_memory"]["Speed"]) / 1e6,
        "gpus": lambda: _gpus_details(lookups["gpus"]),
        "gpu_manufacturer": lambda: _gpu_most_common(server["gpus"], "manufacturer"),
        "gpu_family": lambda: _gpu_most_common(server["gpus"], "family"),
        "gpu_model": lambda: _gpu_most_common(server["gpus"], "model"),
        "gpu_memory_min": lambda: min([gpu["fb_memory"] for gpu in server["gpus"]]),
        "gpu_memory_total": lambda: sum([gpu["fb_memory"] for gpu in server["gpus"]]),
    }
    for k, f in mappings.items():
        try:
            server[k] = f()
        except Exception as e:
            _log_cannot_update_server(server_obj, k, e)

    return server
