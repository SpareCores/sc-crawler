"""Enumerations, JSON nested data objects & other helper classes used in [sc_crawler.tables][]."""

from enum import Enum
from json import dumps
from typing import Any, List, Optional, Union

from pydantic import BaseModel
from sqlalchemy.types import TypeDecorator
from sqlmodel import JSON


class HashableDict(dict):
    """A dict that can be hashed by its JSON representation.

    Useful for typehinting dict-type table columns that are primary
    keys (which need to be hashable for SQLAlchemy ORM). See
    [sc_crawler.table_fields.HashableJSON][] class for the related `sa_type`.
    """

    def __hash__(self):
        return hash(dumps(self, sort_keys=True))


class HashableJSON(TypeDecorator):
    """Alternative JSON SQLAlchemy column representation, which can be hashed."""

    impl = JSON

    def process_result_value(self, value: str, dialect: Any) -> Any:
        if value is None:
            return None
        return HashableDict(value)


class Json(BaseModel):
    """Custom base SQLModel class that supports dumping as JSON."""

    def __json__(self):
        """Call `self.model_dump` to serialize into JSON."""
        return dict(sorted(self.model_dump().items()))


class Status(str, Enum):
    """Last known status of a resource, e.g. active or inactive."""

    ACTIVE = "active"
    """Active and available resource."""
    INACTIVE = "inactive"
    """Inactive resource that is not available anymore."""


class Cpu(Json):
    """CPU details."""

    manufacturer: Optional[str] = None
    """The manufacturer of the processor, e.g. Intel or AMD."""
    family: Optional[str] = None
    """The product line/family of the processor, e.g. Xeon, Core i7, Ryzen 9."""
    model: Optional[str] = None
    """The model number of the processor, e.g. 9750H."""
    cores: Optional[int] = None
    """Number of CPU cores."""
    threads: Optional[int] = None
    """Number of CPU threads."""
    l1_cache_size: Optional[int] = None
    """L1 cache size in bytes."""
    l2_cache_size: Optional[int] = None
    """L2 cache size in bytes."""
    l3_cache_size: Optional[int] = None
    """L3 cache size in bytes."""
    microcode: Optional[str] = None
    """Microcode version."""
    capabilities: List[str] = []
    """List of CPU flag/features/capabilities, e.g. MMX, Intel SGX etc."""
    bugs: List[str] = []
    """List of known bugs, e.g. cpu_meltdown spectre_v1."""
    bogomips: Optional[float] = None
    """BogoMips value."""


class Gpu(Json):
    """GPU accelerator details."""

    manufacturer: str
    """The manufacturer/brand of the GPU accelerator, e.g. Nvidia or AMD."""
    family: Optional[str] = None
    """The model family/architecture of the GPU accelerator."""
    model: Optional[str] = None
    """The model number of the GPU accelerator."""
    memory: int
    """Memory (MiB) allocated to the GPU accelerator."""
    firmware_version: Optional[str] = None
    """Firmware version."""
    bios_version: Optional[str] = None
    """Video BIOS version."""
    graphics_clock: Optional[int] = None
    """GPU core clock speed (Mhz)."""
    sm_clock: Optional[int] = None
    """Streaming Multiprocessor clock speed (Mhz)."""
    mem_clock: Optional[int] = None
    """Memory clock speed (Mhz)."""
    video_clock: Optional[int] = None
    """Video clock speed (Mhz)."""


class StorageType(str, Enum):
    """Type of a storage, e.g. HDD or SSD."""

    HDD = "hdd"
    """Magnetic hard disk drive."""
    SSD = "ssd"
    """Solid-state drive."""
    NVME_SSD = "nvme ssd"
    """NVMe based solid-state drive."""
    NETWORK = "network"
    """Storage over network, e.g. using NFS."""


class Disk(Json):
    """Disk definition based on size and storage type."""

    size: int = 0
    """Storage size in GiB."""
    storage_type: StorageType
    """[Type][sc_crawler.table_fields.StorageType] of the storage."""


class TrafficDirection(str, Enum):
    """Direction of the network traffic."""

    IN = "inbound"
    """Inbound traffic."""
    OUT = "outbound"
    """Outbound traffic."""


class CpuAllocation(str, Enum):
    """CPU allocation methods at cloud vendors."""

    SHARED = "Shared"
    """Shared CPU with other virtual server tenants."""
    BURSTABLE = "Burstable"
    """CPU that can temporarily burst above its baseline performance."""
    DEDICATED = "Dedicated"
    """Dedicated CPU with known performance."""


class CpuArchitecture(str, Enum):
    """CPU architectures."""

    ARM64 = "arm64"
    """64-bit ARM architecture."""
    ARM64_MAC = "arm64_mac"
    """Apple 64-bit ARM architecture."""
    I386 = "i386"
    """32-bit x86 architecture."""
    X86_64 = "x86_64"
    """64-bit x86 architecture."""
    X86_64_MAC = "x86_64_mac"
    """Apple 64-bit x86 architecture."""


class DdrGeneration(str, Enum):
    """Generation of the DDR SDRAM."""

    DDR3 = "DDR3"
    """DDR3 SDRAM."""
    DDR4 = "DDR4"
    """DDR4 SDRAM."""
    DDR5 = "DDR5"
    """DDR5 SDRAM."""


class Allocation(str, Enum):
    """Server allocation options."""

    ONDEMAND = "ondemand"
    """On-demand server."""
    RESERVED = "reserved"
    """Reserved server."""
    SPOT = "spot"
    """Spot/preemptible server."""


class PriceUnit(str, Enum):
    """Supported units for the price tables."""

    YEAR = "year"
    """Price per year."""
    MONTH = "month"
    """Price per month."""
    HOUR = "hour"
    """Price per hour."""
    GIB = "GiB"
    """Price per gibibyte (GiB)."""
    GB = "GB"
    """Price per gigabyte (GB)."""
    GB_MONTH = "GB/month"
    """Price per gigabyte (GB)/month."""


class PriceTier(Json):
    """Price tier definition.

    As standard JSON does not support Inf, NaN etc values,
    those should be passed as string, e.g. for the upper bound.

    See [float_inf_to_str][sc_crawler.utils.float_inf_to_str] for
    converting an infinite numeric value into "Infinity"."""

    lower: Union[float, str]
    """Lower bound of pricing tier, e.g. 100 GB. Unit is defined in the parent object."""
    upper: Union[float, str]
    """Upper bound of pricing tier, e.g. 1 TB. Unit is defined in the parent object."""
    price: float
    """Price in the pricing tier. Currency is defined in the parent object."""
