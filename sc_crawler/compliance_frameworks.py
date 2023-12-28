from .schemas import ComplianceFramework


hipaa = ComplianceFramework(
    id="hipaa",
    name="The Health Insurance Portability and Accountability Act",
    abbreviation="HIPAA",
    description="HIPAA (Health Insurance Portability and Accountability Act) is a U.S. federal law designed to safeguard the privacy and security of individuals' health information, establishing standards for its protection and regulating its use in the healthcare industry.",  # noqa: E501
    homepage="https://www.cdc.gov/phlp/publications/topic/hipaa.html",
)

soc2t2 = ComplianceFramework(
    id="soc2t2",
    name="System and Organization Controls Level 2 Type 2",
    abbreviation="SOC 2 Type 2",
    description="SOC 2 Type 2 is a framework for assessing and certifying the effectiveness of a service organization's information security policies and procedures over time, emphasizing the operational aspects and ongoing monitoring of controls.",  # noqa: E501
    homepage="https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2",  # noqa: E501
)
