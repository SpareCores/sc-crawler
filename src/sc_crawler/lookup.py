from typing import List

from .tables import ComplianceFramework, Country

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
