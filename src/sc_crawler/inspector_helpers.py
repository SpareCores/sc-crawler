import re
import xml.etree.ElementTree as xmltree
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .table_fields import Disk, StorageType

LSCPU_CACHE_FIELDS = {
    "L1d cache:": "L1d",
    "L1i cache:": "L1i",
    "L2 cache:": "L2",
    "L3 cache:": "L3",
}

# lstopo XML object types for each cache level (hwloc type names)
LSTOPO_CACHE_TYPES = {
    "L1d": "L1Cache",
    "L1i": "L1iCache",
    "L2": "L2Cache",
    "L3": "L3Cache",
}


@dataclass
class StorageInfo:
    storage_type: StorageType = None
    storage_size: int = 0
    storages: List[Disk] = field(default_factory=list)


@dataclass
class CpuCacheInfo:
    level: str
    total_bytes: int
    instances: int
    cores_per_domain: float = 0.0
    effective_per_core_bytes: float = 0.0

    @property
    def per_instance_bytes(self) -> int:
        return self.total_bytes // self.instances if self.instances else 0

    def as_dict(self) -> Dict[str, object]:
        def fmt_bytes(n: int) -> Tuple[int, float]:
            return int(n / 1024), n / (1024.0 * 1024.0)

        pi_kib, pi_mib = fmt_bytes(self.per_instance_bytes)
        t_kib, t_mib = fmt_bytes(self.total_bytes)
        return {
            "level": self.level,
            "per_instance_bytes": self.per_instance_bytes,
            "per_instance_KiB": pi_kib,
            "per_instance_MiB": pi_mib,
            "total_bytes": self.total_bytes,
            "total_KiB": t_kib,
            "total_MiB": t_mib,
            "instances": self.instances,
            "cores_per_domain": self.cores_per_domain,
            "effective_per_core_bytes": self.effective_per_core_bytes,
        }


def _parse_cache_data_string(data: str) -> Tuple[int, int]:
    """
    Parse strings like:
      '262144 (4 instances)'
      '67108864 (1 instance)'
      '262144'
    Returns (total_bytes, instances), where instances defaults to 1 if missing.
    """
    m_total = re.match(r"\s*(\d+)", data)
    if not m_total:
        raise ValueError(f"Could not parse total bytes from cache spec: {data!r}")
    total_bytes = int(m_total.group(1))

    m_inst = re.search(r"\((\d+)\s+instance", data)
    instances = int(m_inst.group(1)) if m_inst else 1

    return total_bytes, instances


def _count_cores_under(element: xmltree.Element) -> int:
    """Count Core elements that are descendants of this element."""
    count = 0
    for elem in element.iter():
        if elem.get("type") == "Core":
            count += 1
    return count


def _parse_lstopo_caches(
    lstopo_obj: xmltree.ElementTree,
) -> Optional[Dict[str, List[Tuple[int, int]]]]:
    """
    Parse lstopo XML and return per-level cache list: (size_bytes, num_cores) per cache object.

    Returns None if file missing or not valid XML. Keys: "L1d", "L1i", "L2", "L3".
    """
    if not lstopo_obj or isinstance(lstopo_obj, Exception):
        return None

    root = lstopo_obj.getroot()

    result: Dict[str, List[Tuple[int, int]]] = {
        level: [] for level in LSTOPO_CACHE_TYPES
    }

    for level, hwloc_type in LSTOPO_CACHE_TYPES.items():
        for elem in root.iter():
            if elem.get("type") != hwloc_type:
                continue
            size_str = elem.get("cache_size")
            if not size_str:
                continue
            try:
                size_bytes = int(size_str)
            except ValueError:
                continue
            num_cores = _count_cores_under(elem)
            if num_cores == 0:
                num_cores = 1
            result[level].append((size_bytes, num_cores))

    return result if any(result.values()) else None


def _apply_lstopo_to_caches(
    caches: Dict[str, CpuCacheInfo],
    lstopo_data: Dict[str, List[Tuple[int, int]]],
    total_physical_cores: int,
) -> None:
    """
    Override cache info with lstopo-derived data when available.
    Use this to fix L3 (and L2/L1) domain count and total when the hypervisor
    misreports topology (e.g. one L3 per vCPU instead of shared).
    """
    for level, entries in lstopo_data.items():
        if not entries:
            continue
        total_bytes = sum(s for s, _ in entries)
        instances = len(entries)
        total_cores_in_entries = sum(c for _, c in entries)
        cores_per_domain = total_cores_in_entries / instances if instances else 0.0
        if cores_per_domain <= 0 and total_physical_cores > 0 and instances > 0:
            cores_per_domain = total_physical_cores / instances
        per_inst = total_bytes // instances if instances else 0
        effective = (per_inst / cores_per_domain) if cores_per_domain > 0 else 0.0

        info = caches.setdefault(
            level,
            CpuCacheInfo(level=level, total_bytes=0, instances=0),
        )
        info.total_bytes = total_bytes
        info.instances = instances
        info.cores_per_domain = cores_per_domain
        info.effective_per_core_bytes = effective
        # Preserve per-instance size from lstopo (may differ from lscpu)
        if per_inst != info.per_instance_bytes:
            # CacheInfo stores total_bytes and instances; per_instance_bytes is derived.
            # So we must keep total_bytes and instances as set above; per_instance_bytes
            # will now be total_bytes // instances, which equals per_inst. Good.
            pass


def _get_lscpu_value(lscpu_obj: List, field_name: str) -> Optional[str]:
    for entry in lscpu_obj:
        if entry.get("field") == field_name:
            return entry.get("data")
    return None


def _get_total_physical_cores(lscpu_obj: List) -> int:
    """
    Derive the number of physical cores from lscpu JSON.

    Prefer CPU(s) / Thread(s) per core, fall back to
    Socket(s) * Core(s) per socket if needed.
    """
    cpu_s = _get_lscpu_value(lscpu_obj, "CPU(s):")
    threads_per_core = _get_lscpu_value(lscpu_obj, "Thread(s) per core:")
    if cpu_s and threads_per_core:
        try:
            total_threads = int(cpu_s.split()[0])
            tpc = int(threads_per_core.split()[0])
            if tpc > 0:
                return total_threads // tpc
        except ValueError:
            pass

    sockets = _get_lscpu_value(lscpu_obj, "Socket(s):")
    cores_per_socket = _get_lscpu_value(lscpu_obj, "Core(s) per socket:")
    if sockets and cores_per_socket:
        try:
            return int(sockets.split()[0]) * int(cores_per_socket.split()[0])
        except ValueError:
            pass

    raise ValueError("Unable to determine total physical cores from lscpu JSON")


def _extract_cache_info(
    lscpu_obj: List, total_physical_cores: int
) -> Dict[str, CpuCacheInfo]:
    caches: Dict[str, CpuCacheInfo] = {}

    for entry in lscpu_obj:
        field = entry.get("field")
        data = entry.get("data")
        if field in LSCPU_CACHE_FIELDS and data:
            level = LSCPU_CACHE_FIELDS[field]
            total_bytes, instances = _parse_cache_data_string(data)
            caches[level] = CpuCacheInfo(
                level=level, total_bytes=total_bytes, instances=instances
            )

    # Populate sharing information: how many cores share one cache domain,
    # and the effective per-core cache budget.
    for info in caches.values():
        if info.instances > 0 and total_physical_cores > 0:
            info.cores_per_domain = total_physical_cores / float(info.instances)
            if info.cores_per_domain > 0:
                info.effective_per_core_bytes = (
                    info.per_instance_bytes / info.cores_per_domain
                )

    return caches


def _get_cpu_cache_info(
    lscpu_obj: List, lstopo_obj: xmltree.ElementTree
) -> Dict[str, Dict]:
    total_physical_cores = _get_total_physical_cores(lscpu_obj)
    caches = _extract_cache_info(lscpu_obj, total_physical_cores)
    lstopo_data = _parse_lstopo_caches(lstopo_obj)
    if lstopo_data:
        _apply_lstopo_to_caches(caches, lstopo_data, total_physical_cores)
    return {level: info.as_dict() for level, info in caches.items()}
