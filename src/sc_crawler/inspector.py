import csv
import json
import xml.etree.ElementTree as xmltree
from atexit import register
from functools import cache
from itertools import groupby
from operator import itemgetter
from os import PathLike, getenv, makedirs, path
from re import compile, match, search, sub
from shutil import rmtree
from statistics import mode
from tempfile import mkdtemp
from typing import TYPE_CHECKING, List
from zipfile import ZipFile

from requests import get
from yaml import safe_load as yaml_safe_load

from .logger import logger
from .table_bases import ServerBase
from .table_fields import DdrGeneration

if TYPE_CHECKING:
    from .tables import Server

SERVER_CLIENT_FRAMEWORK_MAPS = {
    "static_web": {
        "keys": ["size", "connections_per_vcpus"],
        "measurements": [
            "rps",
            "rps-extrapolated",
            "throughput",
            "throughput-extrapolated",
            "latency",
        ],
    },
    "redis": {
        "keys": ["operation", "pipeline"],
        "measurements": ["rps", "rps-extrapolated", "latency"],
    },
}

PASSMARK_MAPS = {
    "SUMM_CPU": "CPU Mark",
    "CPU_INTEGER_MATH": "CPU Integer Maths Test",
    "CPU_FLOATINGPOINT_MATH": "CPU Floating Point Maths Test",
    "CPU_PRIME": "CPU Prime Numbers Test",
    "CPU_SORTING": "CPU String Sorting Test",
    "CPU_ENCRYPTION": "CPU Encryption Test",
    "CPU_COMPRESSION": "CPU Compression Test",
    "CPU_SINGLETHREAD": "CPU Single Threaded Test",
    "CPU_PHYSICS": "CPU Physics Test",
    "CPU_MATRIX_MULT_SSE": "CPU Extended Instructions Test",
    "SUMM_ME": "Memory Mark",
    "ME_ALLOC_S": "Database Operations",
    "ME_READ_S": "Memory Read Cached",
    "ME_READ_L": "Memory Read Uncached",
    "ME_WRITE": "Memory Write",
    "ME_LATENCY": "Memory Latency",
}


@cache
def inspector_data_path() -> str | PathLike:
    """Download current inspector data into a temp folder.

    Setting the `SC_CRAWLER_INSPECTOR_DATA_PATH` environment variable will
    override the default path for persistent/cached inspector data access.
    """
    if getenv("SC_CRAWLER_INSPECTOR_DATA_PATH"):
        temp_dir = getenv("SC_CRAWLER_INSPECTOR_DATA_PATH")
        makedirs(temp_dir, exist_ok=True)
    else:
        temp_dir = mkdtemp()
        register(rmtree, temp_dir)
    zip_path = path.join(temp_dir, "downloaded.zip")
    if not path.exists(zip_path):
        response = get(
            "https://github.com/SpareCores/sc-inspector-data/archive/refs/heads/main.zip"
        )
        with open(zip_path, "wb") as f:
            f.write(response.content)
        with ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)
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


def _server_dmidecode_sections(server: "Server", section: str) -> dict:
    return [s["props"] for s in _server_dmidecode(server) if s["name"] == section]


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
                "score": round(float(_server_lscpu_field(server, "BogoMIPS:"))),
            }
        )
    except Exception as e:
        _log_cannot_load_benchmarks(server, framework, e)

    framework = "bw_mem"
    try:
        with open(_server_framework_stdout_path(server, framework), "r") as lines:
            for line in lines:
                # filter out error messages
                if match(r"^(rd|wr|rdwr) \d+(\.\d+) \d+(\.\d+)$", line):
                    row = line.strip().split()
                    benchmarks.append(
                        {
                            **_benchmark_metafields(server, framework=framework),
                            "config": {"operation": row[0], "size": float(row[1])},
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
                        if data[measurement]:
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

    framework = "passmark"
    try:
        with open(_server_framework_stdout_path(server, framework), "r") as fp:
            scores = yaml_safe_load(fp)
        passmark_version = ".".join(
            [str(scores["Version"][i]) for i in ["Major", "Minor", "Build"]]
        )
        for key, name in PASSMARK_MAPS.items():
            benchmarks.append(
                {
                    **_benchmark_metafields(
                        server,
                        benchmark_id=":".join(
                            [framework, sub(r"\W+", "_", name.lower())]
                        ),
                    ),
                    "config": {"framework_version": passmark_version},
                    "score": float(scores["Results"][key]),
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
    # TODO deprecate
    try:
        cores_per_path = {"stressng": server.vcpus, "stressngsinglecore": 1}
        for cores_path in cores_per_path.keys():
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
                        "cores": cores_per_path[cores_path],
                        "framework_version": stressng_version,
                    },
                    "score": float(line.split(": ")[1]),
                }
            )
    except Exception:
        # backfill with newer method - can be dropped once we deprecate stress_ng:cpu_all
        try:
            records = []
            with open(
                _server_framework_stdout_path(server, "stressngfull"), newline=""
            ) as f:
                rows = csv.reader(f, quoting=csv.QUOTE_NONNUMERIC)
                for row in rows:
                    records.append(row)
            for i in [0, len(records) - 1]:
                stressng_version = _server_framework_meta(server, "stressngfull")[
                    "version"
                ]
                benchmarks.append(
                    {
                        **_benchmark_metafields(
                            server,
                            framework="stressngfull",
                            benchmark_id=":".join([framework, "cpu_all"]),
                        ),
                        "config": {
                            "cores": records[i][0],
                            "framework_version": stressng_version,
                        },
                        "score": records[i][1],
                    }
                )
        except Exception as e:
            _log_cannot_load_benchmarks(server, framework, e, True)

    workload = "div16"
    try:
        records = []
        with open(
            _server_framework_stdout_path(server, "stressngfull"), newline=""
        ) as f:
            rows = csv.reader(f, quoting=csv.QUOTE_NONNUMERIC)
            for row in rows:
                records.append(row)
        for record in records:
            stressng_version = _server_framework_meta(server, "stressngfull")["version"]
            benchmarks.append(
                {
                    **_benchmark_metafields(
                        server,
                        framework="stressngfull",
                        benchmark_id=":".join([framework, workload]),
                    ),
                    "config": {
                        "cores": record[0],
                        "framework_version": stressng_version,
                    },
                    "score": record[1],
                }
            )
        # best single and multi core performance
        bests = {"best1": records[0][1], "bestn": max([r[1] for r in records])}
        for k, v in bests.items():
            benchmarks.append(
                {
                    **_benchmark_metafields(
                        server,
                        framework="stressngfull",
                        benchmark_id=":".join([framework, k]),
                    ),
                    "config": {
                        "framework_version": stressng_version,
                    },
                    "score": v,
                }
            )
    except Exception as e:
        _log_cannot_load_benchmarks(server, framework, e, True)

    for framework in SERVER_CLIENT_FRAMEWORK_MAPS.keys():
        try:
            versions = _server_framework_meta(server, framework)["version"]
            # drop the build number at the end of the redis server version
            if framework == "redis":
                versions = sub(r" build=[a-zA-Z0-9]+", "", versions)

            records = []
            with open(
                _server_framework_stdout_path(server, framework), newline=""
            ) as f:
                rows = csv.DictReader(f, quoting=csv.QUOTE_NONNUMERIC)
                for row in rows:
                    if "connections" in row.keys():
                        row["connections_per_vcpus"] = row["connections"] / server.vcpus
                    records.append(row)

            framework_config = SERVER_CLIENT_FRAMEWORK_MAPS[framework]
            keys = framework_config["keys"]
            measurements = framework_config["measurements"]

            # don't care about threads, keep the records with the highest rps
            records = sorted(records, key=lambda x: (*[x[k] for k in keys], -x["rps"]))
            records = groupby(records, key=itemgetter(*keys))
            records = [next(group) for _, group in records]

            for record in records:
                for measurement in measurements:
                    score_field = measurement.split("-")[0]
                    if score_field == "throughput":
                        score_field = "rps"
                    score = record[score_field]
                    server_usrsys = record["server_usr"] + record["server_sys"]
                    client_usrsys = record["client_usr"] + record["client_sys"]
                    note = (
                        "CPU usage (server/client usr+sys): "
                        f"{round(server_usrsys, 4)}/{round(client_usrsys, 4)}."
                    )
                    if measurement.endswith("-extrapolated"):
                        note += f" Original RPS: {score}."
                        score = round(
                            score / server_usrsys * (server_usrsys + client_usrsys), 2
                        )
                    if measurement.startswith("throughput"):
                        # drop the "k" suffix and multiply by 1024
                        size = int(record["size"][:-1]) * 1024
                        score = score * size
                    benchmarks.append(
                        {
                            **_benchmark_metafields(
                                server,
                                framework=framework,
                                benchmark_id=":".join([framework, measurement]),
                            ),
                            "config": {
                                **{k: record[k] for k in keys},
                                "framework_version": versions,
                            },
                            "score": score,
                            "note": note,
                        }
                    )
        except Exception as e:
            _log_cannot_load_benchmarks(server, framework, e, True)

    framework = "llm_speed"
    try:
        assert _server_framework_meta(server, "llm")["exit_code"] == 0
        llm_speed_version = _server_framework_meta(server, "llm")["version"]
        with open(_server_framework_stdout_path(server, "llm"), "r") as fp:
            for line in fp:
                record = json.loads(line)
                model_name = path.basename(record.get("model_filename", "unknown"))
                measurement = "text_generation"
                if record.get("n_prompt") != 0:
                    measurement = "prompt_processing"
                tokens = record.get("n_prompt") + record.get("n_gen")
                config = {
                    "model": model_name,
                    "tokens": tokens,
                    "framework_version": llm_speed_version,
                }
                benchmarks.append(
                    {
                        **_benchmark_metafields(
                            server,
                            framework="llm",
                            benchmark_id=":".join([framework, measurement]),
                        ),
                        "config": config,
                        "score": float(record["avg_ts"]),
                    }
                )
    except Exception as e:
        _log_cannot_load_benchmarks(server, framework, e, True)

    return benchmarks


def _extract_manufacturer(name: str) -> str:
    """Extract the manufacturer from a CPU model name."""
    nl = name.strip().lower()
    for m in ["Intel", "AMD", "NVIDIA", "Microsoft", "Alibaba", "Ampere", "Hygon"]:
        if m.lower() in nl:
            return m
    for p in ["xeon"]:
        if p in nl:
            return "Intel"
    for p in ["epyc", "turin", "genoa"]:
        if p in nl:
            return "AMD"
    if "yitian" in nl:
        return "Alibaba"
    return None


def _extract_family(name: str) -> str:
    """Extract the family from a CPU model name."""
    nl = name.strip().lower()
    if "xeon" in nl:
        return "Xeon"
    for p in ["epyc", "turin", "genoa"]:
        if p in nl:
            return "EPYC"
    if "ampere" in nl:
        return "Ampere Altra"
    if "yitian" in nl:
        return "Yitian"
    return None


def _standardize_manufacturer(manufacturer):
    if manufacturer == "Advanced Micro Devices, Inc.":
        return "AMD"
    if manufacturer == "Intel(R) Corporation":
        return "Intel"
    if manufacturer in ["Nvidia", "NVIDIA", "Tesla"]:
        return "NVIDIA"
    if manufacturer == "MICROSOFT CORPORATION":
        return "Microsoft"
    if manufacturer in [
        "(invalid)",
        "Not Specified",
        "QEMU",
        "Google",
        "AWS",
        "Amazon EC2",
    ]:
        return None
    # drop the copyright symbol
    manufacturer = sub(r"(\([rRcC]\)|®|©)", "", manufacturer)
    return manufacturer.strip()


def _standardize_cpu_family(family):
    if family in ["Other", "<OUT OF SPEC>"]:
        return None
    for prefix in ["Ampere "]:
        if family.startswith(prefix):
            family = family[len(prefix) :].lstrip()
    return family


def _standardize_cpu_model(model):
    model = model.strip()
    if model in [
        "Not Specified",
        "NotSpecified",
        "(invalid)",
        "GENUINE INTEL(R) 0000",
        "pc-i440fx-9.2",
    ]:
        return None
    for prefix in [
        "Alibaba",
        "Hygon",
        "Intel®",
        "Intel",
        "INTEL",
        "AMD",
        "(R)",
        "Xeon®",
        "Xeon",
        "XEON",
        "EPYC ",
        "EPYC™ ",
        "AWS ",
        "(R)",
        "™",
        "Platinum",
        "PLATINUM",
        "Gold",
        "CPU",
        "Processor",
        "(Ice Lake)",
        "(Cascade Lake)",
        "(Skylake)",
        "(Skylake, IBRS)",
        "(Skylake, IBRS, no TSX)",
        "(Cooper Lake)",
        "(Sapphire Rapid)",
        "(Sapphire Rapids)",
        "(Emerald Rapids)",
        "(EMR)",
        "EMR ",
        "Genoa",
        "Milan",
        "ROME",
        "Turin-C",
        "Turin",
        "Platinum",
        "Gold",
    ]:
        if model.startswith(prefix):
            model = model[len(prefix) :].lstrip()
    # drop trailing "CPU @ 2.50GHz"
    model = sub(r"( CPU)? ?@ \d+\.\d+GHz$", "", model)
    # drop trailing "48-Core Processor" or "48-Core"
    model = sub(r"( \d+-Core)?( Processor)?$", "", model)
    # drop anything after a slash
    model = sub(r"/.*$", "", model)
    # or an odd unicode paren start
    model = sub(r"（.*$", "", model)
    # at least product family is known
    if model == "Intel Core Processor (Haswell, no TSX)":
        return "Haswell"
    if model == "EPYC-Genoa":
        return "Genoa"
    if model == "EPYC-Milan":
        return "Milan"

    if model.strip() == "":
        return None
    return model


def _standardize_gpu_model(model, server=None):
    model = model.strip()
    if model in ["", "0", "NULL", "NA", "N/A"]:
        return None
    for prefix in [
        "NVIDIA ",
        "Tesla ",
        "Radeon Pro ",
        "Gaudi ",
        "Quadro ",
        "GeeForce ",
    ]:
        if model.startswith(prefix):
            model = model[len(prefix) :].lstrip()
    if model == "nvidia-a100-80gb":
        model = "A100-SXM4-80GB"
    if model == "nvidia-b200":
        model = "B200"
    if model == "nvidia-h200-141gb":
        model = "H200"
    if model == "nvidia-rtx-pro-6000":
        model = "RTX Pro 6000"
    if server and server["vendor_id"] and server["server_id"] == "p4de.24xlarge":
        model = "A100-SXM4-40GB"
    if model in ["RTX 5880 Ada", "RTX5880"]:
        return "RTX 5880"
    if model == "RTX6000":
        return "RTX 6000"
    # drop too specific parts
    model = sub(r" NVL$", "", model)
    model = sub(r"-SXM[0-9]-[0-9]*GB$", "", model)
    model = sub(r" [0-9]*GB (HBM3|PCIe)$", "", model)
    return model


def _standardize_gpu_family(server):
    family = server.get("gpu_family")
    if "A100" in server.get("gpu_model"):
        family = "Ampere"
    if "K80" in server.get("gpu_model"):
        family = "Kepler"
    if "H100" in server.get("gpu_model") or "H200" in server.get("gpu_model"):
        family = "Hopper"
    if "V520" in server.get("gpu_model"):
        family = "Radeon Pro Navi"
    if "HL-205" in server.get("gpu_model"):
        family = "Gaudi"
    return family


def _l123_cache(lscpu: dict, level: int):
    if level == 1:
        # don't include instruction cache
        cache = int(_listsearch(lscpu, "field", "L1d cache:")["data"].split(" ")[0])
        if cache > 32 * 1024 * 1024:  # 32 MiB+ is potentially corrupted data
            return None
        return cache
    elif level == 2:
        cache = int(_listsearch(lscpu, "field", "L2 cache:")["data"].split(" ")[0])
        if cache > 512 * 1024 * 1024:  # 512 MiB+ is potentially corrupted data
            return None
        return cache
    elif level == 3:
        cache = int(_listsearch(lscpu, "field", "L3 cache:")["data"].split(" ")[0])
        if cache > 1024 * 1024 * 1024:  # 1 GiB+ is potentially corrupted data
            return None
        return cache
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
        "dmidecode_cpus": lambda: _server_dmidecode_sections(
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

    def lscpu_lookup(field: str):
        return _listsearch(lookups["lscpu"], "field", field)["data"]

    mappings = {
        "cpu_cores": lambda: (
            int(lscpu_lookup("Core(s) per socket:")) * int(lscpu_lookup("Socket(s):"))
        ),
        # use 1st CPU's speed, convert to Ghz
        "cpu_speed": lambda: lookups["dmidecode_cpu"]["Max Speed"] / 1e9,
        "cpu_manufacturer": lambda: _standardize_manufacturer(
            lookups["dmidecode_cpu"]["Manufacturer"]
        ),
        "cpu_family": lambda: _standardize_cpu_family(
            lookups["dmidecode_cpu"]["Family"]
        ),
        "cpu_model": lambda: _standardize_cpu_model(
            lookups["dmidecode_cpu"]["Version"]
        ),
        "cpu_l1_cache": lambda: _l123_cache(lookups["lscpu"], 1),
        "cpu_l2_cache": lambda: _l123_cache(lookups["lscpu"], 2),
        "cpu_l3_cache": lambda: _l123_cache(lookups["lscpu"], 3),
        "cpu_flags": lambda: lscpu_lookup("Flags:").split(" "),
        "memory_generation": lambda: DdrGeneration[lookups["dmidecode_memory"]["Type"]],
        # convert to Mhz
        "memory_speed": lambda: int(lookups["dmidecode_memory"]["Speed"]) / 1e6,
        "gpus": lambda: _gpus_details(lookups["gpus"]),
        "gpu_manufacturer": lambda: _gpu_most_common(server["gpus"], "manufacturer"),
        "gpu_family": lambda: _gpu_most_common(server["gpus"], "family"),
        "gpu_model": lambda: _gpu_most_common(server["gpus"], "model"),
        # skip update if there is no HW-inspected GPU info
        "gpu_count": lambda: len(server["gpus"]) if len(server["gpus"]) else None,
        "gpu_memory_min": lambda: min([gpu["memory"] for gpu in server["gpus"]]),
        "gpu_memory_total": lambda: sum([gpu["memory"] for gpu in server["gpus"]]),
    }
    for k, f in mappings.items():
        try:
            newval = f()
            if newval:
                server[k] = newval
        except Exception as e:
            _log_cannot_update_server(server_obj, k, e)

    # lscpu is a more reliable data source than dmidecode
    if not isinstance(lookups["lscpu"], BaseException):
        cpu_model = lscpu_lookup("Model name:")
        # CPU speed seems to be unreliable as reported by dmidecode,
        # e.g. it's 2Ghz in GCP for all instances
        speed = search(r" @ ([0-9\.]*)GHz$", cpu_model)
        if speed:
            server["cpu_speed"] = speed.group(1)
        # manufacturer data might be more likely to present in lscpu (unstructured)
        # TODO note that we might have prefilled info about manufacturer/family/model in a reliable way
        #      so we might not want to overwrite them here
        for manufacturer in ["Intel", "AMD"]:
            if manufacturer in cpu_model:
                server["cpu_manufacturer"] = manufacturer
        for family in ["Xeon", "EPYC"]:
            if family in cpu_model:
                server["cpu_family"] = family
        model = _standardize_cpu_model(cpu_model)
        if model:
            server["cpu_model"] = model

    # 2 Ghz CPU speed at Google is a lie
    if server["vendor_id"] == "gcp" and server.get("cpu_speed") == 2:
        server["cpu_speed"] = None

    # standardize GPU model
    if server.get("gpu_model"):
        server["gpu_model"] = _standardize_gpu_model(server["gpu_model"], server)
        server["gpu_family"] = _standardize_gpu_family(server)
        if not server.get("gpu_manufacturer") and server["gpu_model"] == "A100":
            server["gpu_manufacturer"] = "NVIDIA"

    return server
