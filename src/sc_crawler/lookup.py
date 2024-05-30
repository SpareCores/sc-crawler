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
            "geekbench_version": "The version of geekbench used to measure the score.",
        },
        measurement=measurement,
    )


benchmarks: List[Benchmark] = [
    Benchmark(
        benchmark_id="bw_mem",
        name="Time memory bandwidth",
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
        "Single-Core Score",
        "A composite score using the weighted arithmetic mean of the subsection scores, which are computed using the geometric mean of the related scores.",
    ),
]
