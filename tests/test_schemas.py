import pytest

from sc_crawler.table_bases import ServerBase, StoragePriceBase
from sc_crawler.table_fields import (
    Cpu,
    Disk,
    Gpu,
    PriceTier,
    PriceUnit,
    Status,
    StorageType,
)
from sc_crawler.tables import Country, Vendor, tables
from sc_crawler.tables_scd import tables_scd


def test_scmodels_have_base():
    """Make sure each SQLModel has a Base Pydantic parent without relations."""
    for model in tables + tables_scd:
        assert hasattr(model, "__validator__")
        schema = model.__validator__
        assert schema.__name__.endswith("Base")
        assert hasattr(model, "__table__")
        assert not hasattr(schema, "__table__")


def test_bad_vendor_definition():
    # TODO ValidationError once SQLModel supports pydantic typehint validation
    with pytest.raises(ValueError):
        Vendor()
        Vendor(vendor_id="foobar")
        Vendor(vendor_id="foobar", name="foobar")
        Vendor(vendor_id="foobar", name="foobar", homepage="https://foobar")
        Vendor(
            vendor_id="foobar",
            name="foobar",
            homepage="https://foobar",
            country=Country(country_id="US"),
        )
    with pytest.raises(NotImplementedError):
        Vendor(
            vendor_id="foobar",
            name="foobar",
            homepage="https://foobar",
            country=Country(country_id="US"),
            founding_year=2042,
        ).inventory_regions()


def test_aws():
    from sc_crawler import tables, vendors

    assert isinstance(vendors.aws, tables.Vendor)
    assert vendors.aws.founding_year == 2002


def test_server_gpus_validator_with_dicts():
    """Test that gpus field validator converts dicts to Gpu instances."""
    server = ServerBase(
        vendor_id="test",
        server_id="test-server",
        name="Test Server",
        api_reference="test-ref",
        display_name="Test Server",
        description="A test server",
        vcpus=4,
        memory_amount=8192,
        gpu_count=2,
        storage_size=100,
        status=Status.ACTIVE,
        gpus=[
            {
                "manufacturer": "NVIDIA",
                "model": "T4",
                "memory": 16384,
                "family": "Turing",
                "firmware_version": None,
                "bios_version": None,
                "graphics_clock": None,
                "sm_clock": None,
                "mem_clock": None,
                "video_clock": None,
            },
            {
                "manufacturer": "AMD",
                "model": "MI100",
                "memory": 32768,
                "family": "CDNA",
                "firmware_version": None,
                "bios_version": None,
                "graphics_clock": None,
                "sm_clock": None,
                "mem_clock": None,
                "video_clock": None,
            },
        ],
    )

    assert len(server.gpus) == 2
    assert all(isinstance(gpu, Gpu) for gpu in server.gpus)
    assert server.gpus[0].manufacturer == "NVIDIA"
    assert server.gpus[0].model == "T4"
    assert server.gpus[0].memory == 16384
    assert server.gpus[1].manufacturer == "AMD"
    assert server.gpus[1].model == "MI100"
    assert server.gpus[1].memory == 32768


def test_server_gpus_validator_with_empty_list():
    """Test that gpus field handles empty list correctly."""
    server = ServerBase(
        vendor_id="test",
        server_id="test-server",
        name="Test Server",
        api_reference="test-ref",
        display_name="Test Server",
        description="A test server",
        vcpus=4,
        memory_amount=8192,
        gpu_count=0,
        storage_size=100,
        status=Status.ACTIVE,
        gpus=[],
    )

    assert server.gpus == []


def test_server_storages_validator_with_dicts():
    """Test that storages field validator converts dicts to Disk instances."""
    server = ServerBase(
        vendor_id="test",
        server_id="test-server",
        name="Test Server",
        api_reference="test-ref",
        display_name="Test Server",
        description="A test server",
        vcpus=4,
        memory_amount=8192,
        gpu_count=0,
        storage_size=500,
        status=Status.ACTIVE,
        storages=[
            {"size": 100, "storage_type": "ssd", "description": "boot disk"},
            {"size": 400, "storage_type": "nvme ssd", "description": "data disk"},
        ],
    )

    assert len(server.storages) == 2
    assert all(isinstance(disk, Disk) for disk in server.storages)
    assert server.storages[0].size == 100
    assert server.storages[0].storage_type == StorageType.SSD
    assert server.storages[0].description == "boot disk"
    assert server.storages[1].size == 400
    assert server.storages[1].storage_type == StorageType.NVME_SSD
    assert server.storages[1].description == "data disk"


def test_server_storages_validator_with_empty_list():
    """Test that storages field handles empty list correctly."""
    server = ServerBase(
        vendor_id="test",
        server_id="test-server",
        name="Test Server",
        api_reference="test-ref",
        display_name="Test Server",
        description="A test server",
        vcpus=4,
        memory_amount=8192,
        gpu_count=0,
        storage_size=0,
        status=Status.ACTIVE,
        storages=[],
    )

    assert server.storages == []


def test_server_cpus_validator_with_dicts():
    """Test that cpus field validator converts dicts to Cpu instances."""
    server = ServerBase(
        vendor_id="test",
        server_id="test-server",
        name="Test Server",
        api_reference="test-ref",
        display_name="Test Server",
        description="A test server",
        vcpus=8,
        memory_amount=16384,
        gpu_count=0,
        storage_size=100,
        status=Status.ACTIVE,
        cpus=[
            {
                "manufacturer": "Intel",
                "family": "Xeon",
                "model": "E5-2680 v4",
                "cores": 14,
                "threads": 28,
                "l1_cache_size": 32768,
                "l2_cache_size": 262144,
                "l3_cache_size": 35651584,
                "microcode": "0xb000040",
                "capabilities": ["sse4_2", "avx", "avx2"],
                "bugs": [],
                "bogomips": 5600.0,
            }
        ],
    )

    assert len(server.cpus) == 1
    assert isinstance(server.cpus[0], Cpu)
    assert server.cpus[0].manufacturer == "Intel"
    assert server.cpus[0].family == "Xeon"
    assert server.cpus[0].model == "E5-2680 v4"
    assert server.cpus[0].cores == 14
    assert server.cpus[0].threads == 28
    assert "avx2" in server.cpus[0].capabilities


def test_server_cpus_validator_with_empty_list():
    """Test that cpus field handles empty list correctly."""
    server = ServerBase(
        vendor_id="test",
        server_id="test-server",
        name="Test Server",
        api_reference="test-ref",
        display_name="Test Server",
        description="A test server",
        vcpus=4,
        memory_amount=8192,
        gpu_count=0,
        storage_size=100,
        status=Status.ACTIVE,
        cpus=[],
    )

    assert server.cpus == []


def test_storage_price_tiered_validator_with_dicts():
    """Test that price_tiered field validator converts dicts to PriceTier instances."""
    storage_price = StoragePriceBase(
        vendor_id="test",
        region_id="us-east-1",
        storage_id="standard-ssd",
        unit=PriceUnit.GB_MONTH,
        price=0.15,
        price_upfront=0,
        currency="USD",
        status=Status.ACTIVE,
        price_tiered=[
            {"lower": 0, "upper": 100, "price": 0.20},
            {"lower": 100, "upper": 1000, "price": 0.15},
            {"lower": 1000, "upper": "Infinity", "price": 0.10},
        ],
    )

    assert len(storage_price.price_tiered) == 3
    assert all(isinstance(tier, PriceTier) for tier in storage_price.price_tiered)
    assert storage_price.price_tiered[0].lower == 0
    assert storage_price.price_tiered[0].upper == 100
    assert storage_price.price_tiered[0].price == 0.20
    assert storage_price.price_tiered[1].lower == 100
    assert storage_price.price_tiered[1].upper == 1000
    assert storage_price.price_tiered[1].price == 0.15
    assert storage_price.price_tiered[2].lower == 1000
    assert storage_price.price_tiered[2].upper == float("inf")
    assert storage_price.price_tiered[2].price == 0.10


def test_storage_price_tiered_validator_with_empty_list():
    """Test that price_tiered field validator handles empty list correctly."""
    storage_price = StoragePriceBase(
        vendor_id="test",
        region_id="ap-southeast-1",
        storage_id="standard-hdd",
        unit=PriceUnit.GB_MONTH,
        price=0.08,
        price_upfront=0,
        currency="USD",
        status=Status.ACTIVE,
        price_tiered=[],
    )

    # Verify that empty list is preserved
    assert storage_price.price_tiered == []


def test_storage_price_tiered_validator_with_mixed_bounds():
    """Test that price_tiered field validator handles mixed numeric and string bounds."""
    storage_price = StoragePriceBase(
        vendor_id="test",
        region_id="us-east-2",
        storage_id="tiered-storage",
        unit=PriceUnit.GB_MONTH,
        price=0.12,
        price_upfront=0,
        currency="USD",
        status=Status.ACTIVE,
        # Mix of numeric and string bounds
        price_tiered=[
            {"lower": 0.0, "upper": 50.5, "price": 0.18},
            {"lower": 50.5, "upper": 200.0, "price": 0.14},
            {"lower": "200.0", "upper": "Infinity", "price": 0.12},
        ],
    )

    assert len(storage_price.price_tiered) == 3
    assert all(isinstance(tier, PriceTier) for tier in storage_price.price_tiered)
    assert storage_price.price_tiered[0].lower == 0.0
    assert storage_price.price_tiered[0].upper == 50.5
    assert storage_price.price_tiered[1].lower == 50.5
    assert storage_price.price_tiered[1].upper == 200.0
    assert storage_price.price_tiered[2].lower == 200.0
    assert storage_price.price_tiered[2].upper == float("inf")
