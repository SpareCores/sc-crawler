from .tables import ComplianceFramework, Country

# country codes: https://en.wikipedia.org/wiki/ISO_3166-1#Codes
# mapping: https://github.com/manumanoj0010/countrydetails/blob/master/Countrydetails/data/continents.json  # noqa: E501
country_continent_mapping = {
    "AE": "Asia",
    "AU": "Oceania",
    "BH": "Asia",
    "BR": "South America",
    "CA": "North America",
    "CH": "Europe",
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
    "SE": "Europe",
    "SG": "Asia",
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
    # TODO add more e.g.
    # soc2t1
    # iso27001
    # iso27701
    # gdpr
    # pci
    # ccpa
    # csa
}
"""Dictionary of [sc_crawler.tables.ComplianceFramework][] instances keyed by the `compliance_framework_id`."""
