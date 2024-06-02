from re import sub
from typing import List

from .tables import Benchmark, ComplianceFramework, Country

# country codes: https://en.wikipedia.org/wiki/ISO_3166-1#Codes
# mapping: https://github.com/manumanoj0010/countrydetails/blob/master/Countrydetails/data/continents.json  # noqa: E501
country_continent_mapping = {
    "AE": "Asia",
    "AU": "Oceania",
    "BE": "Europe",
    "BH": "Asia",
    "BR": "South America",
    "CA": "North America",
    "CH": "Europe",
    "CL": "South America",
    "CN": "Asia",
    "DE": "Europe",
    "ES": "Europe",
    "FI": "Europe",
    "FR": "Europe",
    "GB": "Europe",
    "HK": "Asia",
    "ID": "Asia",
    "IE": "Europe",
    "IL": "Asia",
    "IT": "Europe",
    "IN": "Asia",
    "JP": "Asia",
    "KR": "Asia",
    "NL": "Europe",
    "PL": "Europe",
    "QA": "Asia",
    "SA": "Asia",
    "SE": "Europe",
    "SG": "Asia",
    "TW": "Asia",
    "US": "North America",
    "ZA": "Africa",
}


countries: dict = {
    k: Country(country_id=k, continent=v) for k, v in country_continent_mapping.items()
}
"""Dictionary of [sc_crawler.tables.Country][] instances keyed by the `country_id`."""

# ##############################################################################


compliance_frameworks: dict = {
    "hipaa": ComplianceFramework(
        compliance_framework_id="hipaa",
        name="The Health Insurance Portability and Accountability Act",
        abbreviation="HIPAA",
        description="HIPAA (Health Insurance Portability and Accountability Act) is a U.S. federal law designed to safeguard the privacy and security of individuals' health information, establishing standards for its protection and regulating its use in the healthcare industry.",  # noqa: E501
        homepage="https://www.cdc.gov/phlp/publications/topic/hipaa.html",
    ),
    "soc2t2": ComplianceFramework(
        compliance_framework_id="soc2t2",
        name="System and Organization Controls Level 2 Type 2",
        abbreviation="SOC 2 Type 2",
        description="SOC 2 Type 2 is a framework for assessing and certifying the effectiveness of a service organization's information security policies and procedures over time, emphasizing the operational aspects and ongoing monitoring of controls.",  # noqa: E501
        homepage="https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2",  # noqa: E501
    ),
    "iso27001": ComplianceFramework(
        compliance_framework_id="iso27001",
        name="ISO/IEC 27001",
        abbreviation="ISO 27001",
        description="ISO 27001 is standard for information security management systems.",  # noqa: E501
        homepage="https://www.iso.org/standard/27001",  # noqa: E501
    ),
    # TODO add more e.g.
    # soc2t1
    # iso27701
    # gdpr
    # pci
    # ccpa
    # csa
}
"""Dictionary of [sc_crawler.tables.ComplianceFramework][] instances keyed by the `compliance_framework_id`."""


def map_compliance_frameworks_to_vendor(
    vendor_id: str, compliance_framework_ids: List[str]
) -> dict:
    """Map compliance frameworks to vendors in a dict.

    Args:
        vendor_id: identifier of a [Vendor][sc_crawler.tables.Vendor]
        compliance_framework_ids: identifier(s) of [`ComplianceFramework`][sc_crawler.tables.ComplianceFramework]

    Returns:
        Array of dictionaroes that can be passed to [sc_crawler.insert.insert_items][].
    """
    items = []
    for compliance_framework_id in compliance_framework_ids:
        items.append(
            {
                "vendor_id": vendor_id,
                "compliance_framework_id": compliance_framework_id,
            }
        )
    return items


def _geekbenchmark(name: str, description: str):
    measurement = sub(r"\W+", "_", name.lower())
    return Benchmark(
        benchmark_id="geekbench:" + measurement,
        name="Geekbench: " + name,
        description=(
            description
            + "The score is calibrated against a baseline score of 2,500 (Dell Precision 3460 with a Core i7-12700 processor) as per the Geekbench 6 Benchmark Internals."
        ),
        framework="geekbench",
        config_fields={
            "cores": "Single-Core or Multi-Core peformance tests.",
            "framework_version": "Version number of geekbench.",
        },
        measurement=measurement,
    )


benchmarks: List[Benchmark] = [
    Benchmark(
        benchmark_id="bogomips",
        name="BogoMips",
        description='A crude measurement of CPU speed by the Linux kernel. This is NOT usable for performance comparisons among different CPUs, but might be useful to check if a processor is in the range of similar processors. As often quoted, BogoMips measures "the number of million times per second a processor can do absolutely nothing".',
        framework="bogomips",
        unit="MIPS",
    ),
    Benchmark(
        benchmark_id="bw_mem",
        name="Memory bandwidth",
        description="bw_mem allocates twice the specified amount of memory, zeros it, and then times the copying of the first half to the second half. Results are reported in megabytes moved per second (MB/sec). bw_mem is provided by lmbench. For more details, see the man pages.",
        framework="bw_mem",
        config_fields={
            "what": "The type of measurement: 'rd' measures the time to read data into the processor, 'wr' measures the time to write data to memory, and 'rdwr' measures the time to read data into memory and then write data to the same memory location.",
            "size": "Amount of memory to be used in MB",
        },
        unit="MB/sec",
    ),
    Benchmark(
        benchmark_id="compression_text:ratio",
        name="Compression ratio",
        description="Measures the compression ratio while compressing the dickens.txt of the Silesia corpus (10 MB uncompressed) using various algorithms, compressions levels and other extra arguments.",
        framework="compression_text",
        config_fields={
            "algo": "Compression algorithm, e.g. brotli or bz2.",
            "compression_level": "Compression level/quality/level.",
            "threads": "Number of threads/workers.",
            "block_size": "Block size",
        },
        measurement="ratio",
        higher_is_better=False,
    ),
    Benchmark(
        benchmark_id="compression_text:compress",
        name="Compression bandwidth",
        description="Measures the compression bandwidth (bytes/second) on the dickens.txt of the Silesia corpus (10 MB uncompressed) using various algorithms, compressions levels and other extra arguments.",
        framework="compression_text",
        config_fields={
            "algo": "Compression algorithm, e.g. brotli or bz2.",
            "compression_level": "Compression level/quality/level.",
            "threads": "Number of threads/workers.",
            "block_size": "Block size",
        },
        measurement="compress",
        unit="byte/s",
    ),
    Benchmark(
        benchmark_id="compression_text:decompress",
        name="Decompression bandwidth",
        description="Measures the decompression bandwidth (bytes/second) on the compressed dickens.txt of the Silesia corpus (10 MB uncompressed) using various algorithms, compressions levels and other extra arguments.",
        framework="compression_text",
        config_fields={
            "algo": "Compression algorithm, e.g. brotli or bz2.",
            "compression_level": "Compression level/quality/level.",
            "threads": "Number of threads/workers.",
            "block_size": "Block size",
        },
        measurement="decompress",
        unit="byte/s",
    ),
    _geekbenchmark(
        "Score",
        "Composite score using the weighted arithmetic mean of the subsection scores, which are computed using the geometric mean of the related scores.",
    ),
    _geekbenchmark(
        "File Compression",
        "Compresses and decompresses the Ruby 3.1.2 source archive (a 75 MB archive with 9841 files) using LZ4 and ZSTD on an in-memory encrypted file system. It also verifies the files using SHA1.",
    ),
    _geekbenchmark(
        "Navigation",
        "Generates 24 different routes between a sequence of locations on two OpenStreetMap maps (one for a small city, one for a large city) using Dijkstra's algorithm.",
    ),
    _geekbenchmark(
        "HTML5 Browser",
        "Opens and renders web pages (8 in single-core mode, 32 in multi-core mode) using a headless web browser.",
    ),
    _geekbenchmark(
        "PDF Renderer",
        "Opens complex PDF documents (4 in single-core mode, 16 in multi-core mode) of park maps from the American National Park Service (sizes from 897 KB to 1.5 MB) with large vector images, lines and text.",
    ),
    _geekbenchmark(
        "Photo Library",
        "Categorizes and tags photos (16 in single-core mode, 64 in multi-core mode) based on the objects that they contain. The workload performs JPEG decompression, thumbnail generation, image transformations, image classification (using MobileNet 1.0), and storing data in SQLite.",
    ),
    _geekbenchmark(
        "Clang",
        "Compiles files (8 in single-core mode, 96 in multi-core mode) of the Lua interpreter using Clang and the musl libc as the C standard library for the compiled files.",
    ),
    _geekbenchmark(
        "Text Processing",
        "Loads 190 markdown files, parses the contents using regular expressions, stores metadata in a SQLite database, and exports the content to a different format on an in-memory encrypted file system, using a mix of C++ and Python.",
    ),
    _geekbenchmark(
        "Asset Compression",
        "Compresses 16 texture images and geometry files using ASTC, BC7, DXTC, and Draco.",
    ),
    _geekbenchmark(
        "Object Detection",
        "Detects and classifies objects in 300x300 pixel photos (16 in single-core mode, 64 in multi-core mode) using the MobileNet v1 SSD convolutional neural network.",
    ),
    _geekbenchmark(
        "Background Blur",
        "Separates and nlurs the background of 10 frames in a 1080p video, using DeepLabV3+.",
    ),
    _geekbenchmark(
        "Horizon Detection",
        "Detects and straightens uneven or crooked horizon lines in a 48MP photo to make it look more realistic, using the Canny edge detector and the Hough transform.",
    ),
    _geekbenchmark(
        "Object Remover",
        "Removes an object (using a mask) from a 3MP photo, and fills in the gap left behind using the iterative PatchMatch Inpainting approach (Barnes et al. 2009).",
    ),
    _geekbenchmark(
        "HDR",
        "Blends six 16MP SDR photos to create a single HDR photo, using a recovery process and radiance map construction (Debevec and Malik 1997), and a tone mapping algorithm (Reinhard and Devlin 2005).",
    ),
    _geekbenchmark(
        "Photo Filter",
        "Applies colour and blur filters, level adjustments, cropping, scaling, and image compositing filters to 10 photos range in size from 3 MP to 15 MP",
    ),
    _geekbenchmark(
        "Ray Tracer",
        "Renders the Blender BMW scene using a custom ray tracer built with the Intel Embree ray tracing library.",
    ),
    _geekbenchmark(
        "Structure from Motion",
        "Generates 3D geometry by constructing the coordinates of the points that are visible in nine 2D images of the same scene.",
    ),
    Benchmark(
        benchmark_id="openssl",
        name="OpenSSL speed",
        description="Measures the performance of OpenSSL's selected hash functions and block ciphers with different block sizes of data.",
        framework="openssl",
        config_fields={
            "algo": "Hash or block cipher algorithm, e.g. sha256 or aes-256-cbc.",
            "block_size": "Block size (byte).",
            "framework_version": "Version number of OpenSSL.",
        },
        unit="byte/s",
    ),
    Benchmark(
        benchmark_id="stress_ng:cpu_all",
        name="stress-ng CPU all",
        description="Stress the CPU with all available methods supported by stress-ng, and count the total bogo operations per second based on wall clock run time. The stress methods include bit operations, recursive calculations, integer divisions, floating point operations, matrix multiplication, stats, trigonometric, and hash functions.",
        framework="stress_ng",
        measurement="cpu_all",
        config_fields={
            "cores": "Stressing a single core or all cores.",
            "framework_version": "Version number of stress-ng.",
        },
        unit="bogo ops/s (real time)",
    ),
]
