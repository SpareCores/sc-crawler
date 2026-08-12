import warnings

import pytest

from sc_crawler.table_bases import ServerBase, ServerDescriptionFields, StoragePriceBase
from sc_crawler.table_fields import (
    Category,
    Cpu,
    Disk,
    Gpu,
    PriceTier,
    PriceUnit,
    Status,
    StorageType,
)
from sc_crawler.tables import (
    BenchmarkScore,
    Country,
    Database,
    DatabasePrice,
    DatabaseStoragePrice,
    StoragePrice,
    Vendor,
    tables,
)
from sc_crawler.tables_scd import tables_scd


def test_scmodels_have_base():
    """Make sure each SQLModel has a Base Pydantic parent without relations."""
    for model in tables + tables_scd:
        assert hasattr(model, "__validator__")
        schema = model.__validator__
        assert schema.__name__.endswith("Base")
        assert hasattr(model, "__table__")
        assert not hasattr(schema, "__table__")


def test_benchmark_score_primary_keys_include_resource_discriminator():
    assert BenchmarkScore.get_columns()["primary_keys"] == [
        "vendor_id",
        "benchmark_id",
        "resource_type",
        "resource_id",
        "config",
    ]
    cols = BenchmarkScore.get_columns()["all"]
    assert "server_id" not in cols
    assert "database_id" not in cols
    assert "kernel_version" not in cols
    assert "environment" in cols
    assert BenchmarkScore.get_table_name() == "benchmark_score"
    assert "database_benchmark_score" not in [t.get_table_name() for t in tables]


def test_database_price_primary_keys_match_storage_price_shape():
    assert DatabasePrice.get_columns()["primary_keys"] == [
        "vendor_id",
        "region_id",
        "database_id",
        "allocation",
        "ha",
        "ha_strategy",
    ]
    assert DatabaseStoragePrice.get_columns()["primary_keys"] == [
        "vendor_id",
        "region_id",
        "database_storage_id",
    ]
    assert "unit" not in DatabasePrice.get_columns()["primary_keys"]
    assert "unit" not in DatabaseStoragePrice.get_columns()["primary_keys"]
    assert StoragePrice.get_columns()["primary_keys"] == [
        "vendor_id",
        "region_id",
        "storage_id",
    ]


def test_database_columns_include_ha_strategy_after_ha():
    cols = Database.get_columns()["all"]
    assert cols.index("ha_strategy") == cols.index("ha") + 1


def test_database_columns_include_api_reference_object_after_api_reference():
    cols = Database.get_columns()["all"]
    assert cols.index("api_reference_object") == cols.index("api_reference") + 1


def test_database_columns_use_storage_size_only():
    cols = Database.get_columns()["all"]
    assert "storage_size" in cols
    assert "storage_size_min" not in cols
    assert "storage_size_max" not in cols
    assert "storage_type" not in cols


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


def test_server_description_categories_validator_with_strings():
    """Test that categories field validator converts strings to Category instances."""
    description = ServerDescriptionFields(
        page=["word " * 50],
        description="word " * 100,
        og_description="x" * 200,
        meta_description="x" * 150,
        tagline="word " * 20,
        bullet_points=["a", "b", "c", "d"],
        categories=["General Purpose", "Compute Optimized"],
    )

    assert len(description.categories) == 2
    assert all(isinstance(category, Category) for category in description.categories)
    assert description.categories[0] == Category.GENERAL_PURPOSE
    assert description.categories[1] == Category.COMPUTE_OPTIMIZED

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        dumped = description.model_dump()
        assert dumped["categories"] == [
            Category.GENERAL_PURPOSE,
            Category.COMPUTE_OPTIMIZED,
        ]
        assert not caught

    reconstructed = ServerDescriptionFields.model_construct(
        page=description.page,
        description=description.description,
        og_description=description.og_description,
        meta_description=description.meta_description,
        tagline=description.tagline,
        bullet_points=description.bullet_points,
        categories=["General Purpose", "Compute Optimized"],
    )
    reconstructed._reconstruct_categories()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        reconstructed.model_dump()
        assert not caught


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


def test_validate_items_keeps_datetime_objects():
    from datetime import UTC, datetime

    from sc_crawler.insert import validate_items
    from sc_crawler.tables import Server

    observed_at = datetime.now(UTC)
    validated = validate_items(
        Server,
        [
            {
                "vendor_id": "aws",
                "server_id": "t3.small",
                "name": "t3.small",
                "api_reference": "t3.small",
                "display_name": "t3.small",
                "description": "test",
                "family": "t3",
                "vcpus": 2,
                "cpus": [],
                "gpus": [],
                "storages": [],
                "cpu_flags": [],
                "status": Status.ACTIVE,
                "observed_at": observed_at,
            }
        ],
    )[0]

    assert isinstance(validated["observed_at"], datetime)
    assert validated["observed_at"] == observed_at


def test_benchmark_score_key_translation_and_hybrids():
    from sqlmodel import select

    from sc_crawler.table_bases import BenchmarkScoreBase
    from sc_crawler.table_fields import ResourceType

    server_item = BenchmarkScoreBase.model_validate(
        {
            "vendor_id": "aws",
            "server_id": "m5.large",
            "benchmark_id": "bogomips",
            "config": {},
            "score": 1.0,
            "environment": {"kernel_version": "6.8.0"},
        }
    )
    assert server_item.resource_type == ResourceType.SERVER
    assert server_item.resource_id == "m5.large"
    assert server_item.server_id == "m5.large"
    assert server_item.database_id is None

    response = server_item.to_response()
    assert response == {
        "vendor_id": "aws",
        "benchmark_id": "bogomips",
        "config": {},
        "framework_version": None,
        "score": 1.0,
        "score_breakdown": None,
        "note": None,
        "status": server_item.status,
        "observed_at": server_item.observed_at,
        "server_id": "m5.large",
        "kernel_version": "6.8.0",
    }
    assert "database_id" not in response
    assert "resource_type" not in response
    assert "resource_id" not in response
    assert "environment" not in response

    db_item = BenchmarkScoreBase.model_validate(
        {
            "vendor_id": "aws",
            "database_id": "db.m5.large",
            "benchmark_id": "pgbench",
            "config": {},
            "score": 2.0,
            "environment": {"database_engine_version": "16.3"},
        }
    )
    assert db_item.resource_type == ResourceType.DATABASE
    assert db_item.server_id is None
    assert db_item.database_id == "db.m5.large"

    db_response = db_item.to_response()
    assert db_response["database_id"] == "db.m5.large"
    assert db_response["database_engine_version"] == "16.3"
    assert "server_id" not in db_response
    assert "resource_type" not in db_response
    assert "resource_id" not in db_response
    assert "environment" not in db_response

    bare = BenchmarkScoreBase.model_validate(
        {
            "vendor_id": "aws",
            "server_id": "t3.micro",
            "benchmark_id": "bogomips",
            "config": {},
            "score": 3.0,
        }
    )
    bare_response = bare.to_response()
    assert bare_response["server_id"] == "t3.micro"
    assert "environment" not in bare_response
    assert "kernel_version" not in bare_response

    constructed = BenchmarkScoreBase.model_construct(
        vendor_id="aws",
        resource_type="server",
        resource_id="m5.large",
        benchmark_id="bogomips",
        config={},
        score=4.0,
        environment={"server_id": "env-should-not-win", "kernel_version": "6.1.0"},
    )
    constructed_response = constructed.to_response()
    assert constructed_response["server_id"] == "m5.large"
    assert constructed_response["kernel_version"] == "6.1.0"

    filter_sql = str(select(BenchmarkScore).where(BenchmarkScore.server_id == "x"))
    assert "resource_type" in filter_sql
    assert "resource_id" in filter_sql

    select_sql = str(select(BenchmarkScore.server_id, BenchmarkScore.database_id))
    assert "AS server_id" in select_sql
    assert "AS database_id" in select_sql


def test_benchmark_score_rejects_both_ids():
    from pydantic import ValidationError

    from sc_crawler.table_bases import BenchmarkScoreBase

    try:
        BenchmarkScoreBase.model_validate(
            {
                "vendor_id": "aws",
                "server_id": "m5.large",
                "database_id": "db.m5.large",
                "benchmark_id": "bogomips",
                "config": {},
                "score": 1.0,
            }
        )
    except ValidationError as e:
        assert "only one of server_id or database_id" in str(e)
    else:
        raise AssertionError("expected ValidationError")


def test_status_retired_only_allowed_on_server_and_database():
    from pydantic import ValidationError

    from sc_crawler.table_bases import DatabaseBase, VendorBase

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
        status=Status.RETIRED,
    )
    assert server.status == Status.RETIRED

    database = DatabaseBase(
        vendor_id="test",
        database_id="db.test",
        name="db.test",
        api_reference="db.test",
        display_name="db.test",
        description="A test database",
        status=Status.PLANNED_FOR_RETIREMENT,
    )
    assert database.status == Status.PLANNED_FOR_RETIREMENT

    with pytest.raises(ValidationError, match="only valid for Server and Database"):
        VendorBase(
            vendor_id="test",
            name="Test",
            country_id="US",
            founding_year=2000,
            status=Status.RETIRED,
        )

    with pytest.raises(ValidationError, match="only valid for Server and Database"):
        StoragePriceBase(
            vendor_id="test",
            region_id="us-east-1",
            storage_id="gp3",
            unit=PriceUnit.GB_MONTH,
            price=0.1,
            status=Status.PLANNED_FOR_RETIREMENT,
        )
