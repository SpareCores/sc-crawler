from re import sub
from typing import List

from .tables import Benchmark, ComplianceFramework, Country

# country codes: https://en.wikipedia.org/wiki/ISO_3166-1#Codes
# mapping: https://github.com/manumanoj0010/countrydetails/blob/master/Countrydetails/data/continents.json  # noqa: E501
country_continent_mapping = {
    "AE": "Asia",
    "AT": "Europe",
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
    "MY": "Asia",
    "MX": "North America",
    "NL": "Europe",
    "NO": "Europe",
    "NZ": "Oceania",
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
    "csa-star": ComplianceFramework(
        compliance_framework_id="csa-star",
        name="CSA STAR",
        abbreviation="CSA STAR",
        description="ICSA STAR certification is a new and targeted international professional certification program by the founders of global standards - the British Standards Institution (BSI) and the international Cloud Security Alliance (CSA), aimed at coping with specific problems related to cloud security.",  
        homepage="https://cloudsecurityalliance.org/star/",  
    ),
    "iso20000": ComplianceFramework(
        compliance_framework_id="iso20000",
        name="ISO 20000",
        abbreviation="ISO 20000",
        description="ISO/IEC 20000-1 is a service management system (SMS) standard. It specifies requirements for the service provider to plan, establish, implement, operate, monitor, review, maintain and improve a SMS. The requirements include the design, transition, delivery and improvement of services to fulfil agreed service requirements.",  
        homepage="https://www.iso.org/standard/70636.html?spm=a3c0i.8130068.7278655170.2.1e753c7e9Ih2CA",  
    ),
    "iso22301": ComplianceFramework(
        compliance_framework_id="iso22301",
        name="ISO 22301",
        abbreviation="ISO 22301",
        description="ISO 22301 is the international standard for Business Continuity Management Systems (BCMS). It provides a framework for organizations to plan, establish, implement, operate, monitor, review, maintain, and continually improve a documented management system to protect against, reduce the likelihood of, and ensure recovery from disruptive incidents.",  
        homepage="https://www.iso.org/standard/75106.html?spm=a3c0i.8130079.9155772270.2.421311ea4aOtOL",  
    ),
    "iso9001": ComplianceFramework(
        compliance_framework_id="iso9001",
        name="ISO 9001",
        abbreviation="ISO 9001",
        description="ISO 9001 is a globally recognized standard for quality management. It helps organizations of all sizes and sectors to improve their performance, meet customer expectations and demonstrate their commitment to quality. Its requirements define how to establish, implement, maintain, and continually improve a quality management system (QMS).",  
        homepage="https://www.iso.org/standard/62085.html?spm=a3c0i.241511.7661120070.2.4bc447d0SugXa5",  
    ),
    "iso27017": ComplianceFramework(
        compliance_framework_id="iso27017",
        name="ISO/IEC 27017",
        abbreviation="ISO/IEC 27017",
        description="ISO/IEC 27017 gives guidelines for information security controls applicable to the provision and use of cloud services by providing: additional implementation guidance for relevant controls specified in ISO/IEC 27002; additional controls with implementation guidance that specifically relate to cloud services.",  
        homepage="https://www.iso.org/standard/43757.html?spm=a3c0i.241515.1156722790.2.1aff1e000dbGDd",  
    ),
    "iso27018": ComplianceFramework(
        compliance_framework_id="iso27018",
        name="ISO/IEC 27018",
        abbreviation="ISO/IEC 27018",
        description="ISO/IEC 27018 establishes commonly accepted control objectives, controls and guidelines for implementing measures to protect Personally Identifiable Information (PII) in accordance with the privacy principles in ISO/IEC 29100 for the public cloud computing environment.",  
        homepage="https://www.iso.org/standard/76559.html?spm=a3c0i.241539.8444330340.2.6fd2ca7cd4H5bP",  
    ),
    "iso27701": ComplianceFramework(
        compliance_framework_id="iso27701",
        name="ISO/IEC 27701",
        abbreviation="ISO/IEC 27701",
        description="ISO/IEC 27701 is an extension to ISO/IEC 27001 and ISO/IEC 27002 for privacy management within the context of the organization. It has considered the mapping of GDPR clauses and other privacy-related standards from the very beginning. An authoritative guideline for the construction of a privacy management system. ISO/IEC 27701 provides guidelines for protecting personal privacy information, and supplements additional regulatory requirements to establish, implement, maintain, and continuously improve privacy information management within the scope of ISMS, reducing the risks faced by private information.",  
        homepage="https://www.iso.org/standard/71670.html?spm=a3c0i.13893391.9291823230.2.73082a87ahmQXY",  
    ),
    "iso29151": ComplianceFramework(
        compliance_framework_id="iso29151",
        name="ISO/IEC 29151",
        abbreviation="ISO/IEC 29151",
        description="ISO/IEC 29151 establishes control objectives, controls and guidelines for implementing controls, to meet the requirements identified by a risk and impact assessment related to the protection of personally identifiable information (PII).",  
        homepage="https://www.iso.org/standard/62726.html?spm=a3c0i.13893403.2026408260.2.5fea1a3cTMnLhA",  
    ),
    "iso27799": ComplianceFramework(
        compliance_framework_id="iso27799",
        name="ISO 27799",
        abbreviation="ISO 27799",
        description="ISO 27799:2016 gives guidelines for organizational information security standards and information security management practices including the selection, implementation and management of controls taking into consideration the organization's information security risk environment(s). ISO 27799:2016 provides implementation guidance for the controls described in ISO/IEC 27002 and supplements them where necessary, so that they can be effectively used for managing health information security.",  
        homepage="https://www.iso.org/standard/62777.html?spm=a3c0i.29781758.5536742710.2.397c4c3e4czUX8",  
    ),
    "iso27040": ComplianceFramework(
        compliance_framework_id="iso27040",
        name="ISO/IEC 27040",
        abbreviation="ISO/IEC 27040",
        description="ISO/IEC 27040:2024 provides detailed technical requirements and guidance on how organizations can achieve an appropriate level of risk mitigation by employing a well-proven and consistent approach to the planning, design, documentation, and implementation of data storage security. Storage security applies to the protection of data both while stored in information and communications technology (ICT) systems and while in transit across the communication links associated with storage. Storage security includes the security of devices and media, management activities related to the devices and media, applications and services, and controlling or monitoring user activities during the lifetime of devices and media, and after end of use or end of life.",  
        homepage="https://www.iso.org/standard/80194.html",  
    ),
    "bs10012": ComplianceFramework(
        compliance_framework_id="bs10012",
        name="BS 10012",
        abbreviation="BS 10012",
        description="BS 10012 sets out the requirements for a personal information management system. It ensures organizations identify and mitigate risks to personal information through implementing the appropriate controls. BS 10012 is written to align with EU GDPR requirements. Obtaining this certification helps organization to demonstrate the level of GDPR compliance.",  
        homepage="https://www.bsigroup.com/en-HK/personal-information-management-bs-10012/?spm=a3c0i.13893413.9625468700.2.33b22911NjHWaQ",  
    ),
    "pci_3ds": ComplianceFramework(
        compliance_framework_id="pci_3ds",
        name="PCI 3DS",
        abbreviation="PCI 3DS",
        description="Three-Domain Secure (3DS or 3-D Secure) is a protocol designed to add additional security layer for card-not-present (CNP) transactions, reducing the likelihood of fraudulent usage of payment cards by providing abilities to authenticate cardholders with card issuers. The three domains consist of the acquirer domain, issuer domain, and the interoperability domain (e.g. payment systems). EMVCo developed a new industry specification, EMV 3-D Secure, which supports new payment channels other than traditional browser-based e-commerce transactions, like app-based transactions.",  
        homepage="https://www.pcisecuritystandards.org/document_library/?category=3DS&document=3DS_standard",  
    ),
    "soc1": ComplianceFramework(
        compliance_framework_id="soc1",
        name="SOC 1",
        abbreviation="SOC 1",
        description="SOC 1 Type 2 Report: This is an independent audit report performed according to the SSAE No. 18 Attestation Standards AT-C section in 320 entitled,Reporting on an Examination of Controls at a Service Organization Relevant to User Entities’ Internal Control Over Financial Reporting about the internal controls to achieve the control objectives defined by Alibaba Cloud.",  
        homepage="https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services?spm=a3c0i.29251670.5536742710.2.7eae44aa1y5Wzx",  
    ),
    "soc2": ComplianceFramework(
        compliance_framework_id="soc2",
        name="SOC 2",
        abbreviation="SOC 2",
        description="SOC 2 Type 2 Report: This report describes Alibaba Cloud’s internal controls based on the specific criteria outlined in DC section 200 entitled, Description Criteria for a Description of a Service Organization’s System in a SOC 2® Report with an opinion from the independent auditor to assure that the controls have been designed and operated effectively to achieve the AICPA Trust Services Criteria relevant to security, availability, and confidentiality outlined in TSP section 100 entitled, Trust Services Criteria for Security, Availability, Processing Integrity, Confidentiality, and Privacy.",  
        homepage="https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services?spm=a3c0i.29252073.5536742710.2.4d4063a28vfsFA",  
    ),
    "soc3": ComplianceFramework(
        compliance_framework_id="soc3",
        name="SOC 3",
        abbreviation="SOC 3",
        description="SOC 3 Report: This is an independent audit report generally describing the service commitments and system requirements of Alibaba Cloud that were designed and operated according to the trust services criteria relevant to security, availability, and confidentiality outlined in TSP section 100 entitled,Trust Services Criteria for Security, Availability, Processing Integrity, Confidentiality, and Privacy (AICPA, Trust Services Criteria.) ",  
        homepage="https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services?spm=a3c0i.87509.5536742710.2.400e50b3KWuB1j",  
    ),
    "mtcs": ComplianceFramework(
        compliance_framework_id="mtcs",
        name="MTCS",
        abbreviation="MTCS",
        description="To encourage the adoption of sound risk management and security practices by Cloud Service Providers (CSPs) through certification, the Multi-Tier Cloud Security (MTCS) Singapore standard was developed under Information Technology Standards Committee (ITSC) for Cloud Service Providers in Singapore.",  
        homepage="https://en.wikipedia.org/wiki/SS584",  
    ),
    "dptm": ComplianceFramework(
        compliance_framework_id="dptm",
        name="DPTM",
        abbreviation="DPTM",
        description="The Data Protection Trustmark (DPTM) is a voluntary enterprise-wide certification for organisations to demonstrate accountable data protection practices. The DPTM Certification Framework was developed based on adopting and aligning it with Singapore’s PDPA and incorporating elements of international benchmarks and best practices. It will help businesses increase their competitive advantage and build trust with their customers and stakeholders. Consumers can rest assured that an organisation certified with the DPTM has put in place responsible data protection practices and will take better care of customers’ personal data.",  
        homepage="https://www.imda.gov.sg/programme-listing/data-protection-trustmark-certification?spm=a3c0i.241535.3130899490.1.138c2703WVNkGb",  
    ),
    "c5": ComplianceFramework(
        compliance_framework_id="c5",
        name="C5",
        abbreviation="C5",
        description="Alibaba Cloud’s commitment to applying the highest levels of compliance in controls and security is shown by meeting the C5 standard that serves not only as a benchmark for the German market, but also increasingly as a benchmark for institutions across Europe. With the attestation, customers in German states can leverage the work performed to comply with stringent local requirements and operate secure workloads using Alibaba Cloud services.",  
        homepage="https://prescientsecurity.com/blogs/c5-standard-what-is-c5-compliance",  
    ),
    "aic4": ComplianceFramework(
        compliance_framework_id="aic4",
        name="AIC4",
        abbreviation="AIC4",
        description="The AI Cloud Service Compliance Criteria Catalog provides AI-specific criteria, which enable an evaluation of the security of an AI service across its lifecycle. The criteria set a baseline level of security, which can be reliably assessed through independent auditors. The catalog has been developed for AI services that are based on standard machine learning methods and iteratively improve their performance by utilizing training data.",  
        homepage="https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/CloudComputing/AIC4/AI-Cloud-Service-Compliance-Criteria-Catalogue_AIC4.pdf?spm=a3c0i.25951807.3427869820.1.33bef647D6bJmi&__blob=publicationFile&v=4",  
    ),
    "tc": ComplianceFramework(
        compliance_framework_id="tc",
        name="Trusted Cloud",
        abbreviation="TC",
        description="The Trusted Cloud label is issued by the Trusted Cloud Competence Network. It is awarded to trustworthy cloud services which meet the minimum requirements with regard to transparency, security, quality and legal compliance.",  
        homepage="https://www.trusted-cloud.de/en/?spm=a3c0i.11217971.7237472600.1.19fd6ec5cyFGIp",  
    ),
    "nesa": ComplianceFramework(
        compliance_framework_id="nesa",
        name="NESA/ISR",
        abbreviation="NESA/ISR",
        description="The National Electronic Security Authority (NESA) is a government body tasked with protecting the UAE’s critical information infrastructure and improving national cybersecurity. Alibaba Cloud meets the set of standards and follows the guidance that NESA has produced for government entities in critical sectors, and was audited by a qualified third-party independent auditor for the P1 level compliance.",  
        homepage="",  
    ),
    "nist": ComplianceFramework(
        compliance_framework_id="nist",
        name="NIST800-53",
        abbreviation="NIST",
        description="The original intention of the NIST SP 800-53 series framework is to protect the information security of the US federal government. Although it is not a formal statutory standard, it has become a widely recognized framework by the US and international security community. It guides organizations to establish an information security risk management framework and to select and formulate information security control measures.",  
        homepage="https://csrc.nist.gov/publications/detail/sp/800-53/rev-5/final",  
    ),
    "mlps_2": ComplianceFramework(
        compliance_framework_id="mlps_2",
        name="CCSP/MLPS",
        abbreviation="CCSP/MLPS",
        description="Introduction to Classified Protection of Cybersecurity (CCSP) 2.0CCSP, which is also known as Multi-Level Protection Scheme (MLPS), is a regulatory scheme designed to protect the cyber security of networks and systems in China. Under China Cybersecurity Law, it is required that the network operator in China must protect the network and the system components from interruption, damage, unauthorized access with a tiered concept to avoid any data leakage, manipulation, and being eavesdropped. It is legally compulsory that all companies and individuals who own, operate, or provide services relating to network and corresponding system components in China to follow the national standards under the CCSP scheme. CCSP was first introduced in 2008 and subsequently updated to CCSP 2.0 in 2019.",  
        homepage="https://www.alibabacloud.com/en/china-gateway/mlps2?_p_lc=1&spm=a3c0i.8130190.4649055020.2.7c0e1272ChthR1",  
    ),
    "itss": ComplianceFramework(
        compliance_framework_id="itss",
        name="ITSS",
        abbreviation="ITSS",
        description="Under the guidance of the Information and Software Service Department of the Ministry of Industry and Information Technology (MIIT), Information Technology Service Sub-association (ITSS) of Chinese Electronics Standardization Association organizes third-party assessment agencies in to carry out the pilot work of cloud computing service capability assessment with reference to national stanadards.",  
        homepage="https://www.itss.cn/web/itss/c/xxcx/cert?spm=a3c0i.14030926.8746723210.1.74ea5a43VPS9fK",  
    ),
    "nisc": ComplianceFramework(
        compliance_framework_id="nisc",
        name="NISC",
        abbreviation="NISC",
        description="National center of Incident readiness and Strategy for Cybersecurity, “NISC” has been established since 2015 which was formerly called National Information Security Center since 2005, under the same abbreviation “NISC”, as a secretariat of the Cybersecurity Strategy Headquarters, working together with the public and private sectors on a variety of activities to create a free, fair and secure cyberspace. NISC plays its leading role as a focal point in coordinating intra-government collaboration and promoting partnerships between industry, academia, and public and private sectors.",  
        homepage="",  
    ),
    "trucs": ComplianceFramework(
        compliance_framework_id="trucs",
        name="TRUCS",
        abbreviation="TRUCS",
        description="TRUCS is a certification for cloud computing services organized by the Data Center Alliance and assessed by the the China Academy of Information and Communications Technology (formerly the Telecommunications Research Institute of the Ministry of Industry and Information Technology). The Data Center Alliance is guided by the Communications Development Department of the Ministry of Industry and Information Technology and jointly initiated by the China Academy of Information and Communications Technology and domestic and foreign Internet companies, telecom operators, software and hardware manufacturers and other units. The core goal of trusted cloud service certification is to establish an evaluation system for cloud services, provide support for users to choose trustworthy and secure cloud services, and ultimately promote the healthy and orderly development of China's cloud computing market.",  
        homepage="",  
    ),
    "ctm": ComplianceFramework(
        compliance_framework_id="ctm",
        name="CTM",
        abbreviation="CTM",
        description="The Cyber Trust Mark is a cybersecurity certification for organisations developed by the Cyber Security Agency of Singapore (CSA). They serve as visible indicators to demonstrate that organisations have put in place good cybersecurity practices to protect their operations and customers against cyber attacks. It also serves to indicate that this organisation has invested significant expertise and resources to manage and protect its Information Technology (IT) infrastructure",  
        homepage="https://www.csa.gov.sg/our-programmes/support-for-enterprises/sg-cyber-safe-programme/cybersecurity-certification-for-organisations/cyber-trust/",  
    ),
    "k-isms": ComplianceFramework(
        compliance_framework_id="k-isms",
        name="K-ISMS",
        abbreviation="K-ISMS",
        description="Korea Information Security Management System (K-ISMS) is a Korean government-backed certification sponsored by Korea Internet and Security Agency (KISA) and affiliated with the Korean Ministry of Science and ICT (MSIT). K-ISMS was introduced in 2002 to meet local legal requirements and ICT environment in Korea based on Article 47 (ISMS certification) in Act on Promotion of Information Communications Network Utilization and Information Protection. The K-ISMS certification evaluates the operation and management of information security management systems (ISMS) by enterprises and organizations, ensuring compliance with Korean laws and standards.",  
        homepage="https://isms.kisa.or.kr/main/ispims/issue/",  
    ),
    "gxp": ComplianceFramework(
        compliance_framework_id="gxp",
        name="GxP",
        abbreviation="GxP",
        description="GxP, short for good practice, denotes a set of standards and regulations tailored to specific fields within the life sciences industry. It encompasses guidelines for various practices such as clinical, laboratory, and manufacturing, among others.",  
        homepage="https://www.fda.gov/regulatory-information/search-fda-guidance-documents/part-11-electronic-records-electronic-signatures-scope-and-application?spm=a3c0i.13650448.8754496680.2.153748cfEui56R",  
    ),
    "tisax": ComplianceFramework(
        compliance_framework_id="tisax",
        name="TISAX",
        abbreviation="TISAX",
        description="The European automotive industry's TISAX (Trusted Information Security Assessment Exchange) certification is a mutually acceptable assessment of the automotive industry's information security assessment and provides a common assessment and exchange mechanism. All relevant companies in the European automotive industry are interested in the influence of TISAX certification in the industry. TISAX was founded by the German Association of the Automotive Industry or VDA (German: Verband der Automobilindustrie e. V.) and regulated by the European Network Exchange (ENX).",  
        homepage="https://enx.com/en-US/enxnetwork/?spm=a3c0i.270355.6740120760.2.3eab544f9QBNF0",  
    ),
    "mpa": ComplianceFramework(
        compliance_framework_id="mpa",
        name="MPA",
        abbreviation="MPA",
        description="The Motion Picture Association (MPA) manages security assessments for entertainment vendor facilities on behalf of its member studios. Using a set of Content Security Best Practices that outline standard controls to help secure content, MPA is continually working to strengthen security processes across production, post-production, marketing, and distribution. They provided a set of Best Practices that are designed to provide current and future third-party vendors with an understanding of general content security expectations, as well as a framework for assessing a facility’s ability to protect a client’s content.",  
        homepage="https://www.motionpictures.org/?spm=a3c0i.8813052.5957072400.1.1df53f50QelIHi",  
    ),
    "sec_rule_17a": ComplianceFramework(
        compliance_framework_id="sec_rule_17a",
        name="SEC Rule-17a",
        abbreviation="SEC Rule-17a",
        description="Under Rule 17a-4, electronic records must be preserved exclusively in a non-rewriteable and non-erasable format. This interpretation further clarifies that broker-dealers employ a storage system that prevents alteration or erasure of the records for the required retention period. Broker-dealers are allowed to preserve records on “electronic storage media.” Rule 17a-4 defines the term “electronic storage media” as any digital storage medium or system. The rule requires the preservation of electronic storage media to be exclusively in a non-rewriteable and non-erasable format. WORM (write once read many) media is used for compliance with the rule.",  
        homepage="",  
    ),
    "ospar": ComplianceFramework(
        compliance_framework_id="ospar",
        name="OSPAR",
        abbreviation="OSPAR",
        description="The Association of Banks in Singapore (ABS) has established the Guidelines on Control Objectives and Procedures for Outsourced Service Providers since 2015 to help Financial Institutions (FIs) to assess whether their service providers maintain the same level of governance over entity-level controls, general IT controls, and service controls as if the FIs managed the services on their own. The ABS guidelines recommend that Singapore FIs select OSPAR (Outsourced Service Provider Audit Report) Audited Outsourced Service Providers.",  
        homepage="https://www.abs.org.sg/industry-guidelines/compliance-and-risk-management/outsourcing?spm=a3c0i.19908508.9107477750.2.21af5e28BYNwuY",  
    ),
    "ferpa": ComplianceFramework(
        compliance_framework_id="ferpa",
        name="FERPA",
        abbreviation="FERPA",
        description="The Family Educational Rights and Privacy Act of 1974 (FERPA), also known as the Buckley Amendment, is a Federal law of the United States of America’s Department of Education. It defines education records and aims to protect privacy of education records by establishing that parents and students have specified rights regarding the access and use of those records. FERPA applies to educational institutions (public schools and state or local education agencies) that receive Federal education funds, and it protects both paper and computerized records. An educational institution “provides educational services or instruction, or both, to students”; whereas an educational agency “is authorized to direct and control public elementary or secondary, or postsecondary educational institutions.”",  
        homepage="https://www.ed.gov/policy/gen/guid/fpco/ferpa/index.html?spm=a3c0i.24097766.3130899490.1.7c764726QMhKXt",  
    ),
    "coppa": ComplianceFramework(
        compliance_framework_id="coppa",
        name="COPPA",
        abbreviation="COPPA",
        description="The Children’s Online Privacy Protection Act (COPPA) is a Federal law of the United States of America (US) enacted by the US Congress in 1998 and since amended in 2013. It defines personal information (as applied to children’s personal information or ‘covered information’) and aims to protect children under age 13 by affording certain rights to parents regarding the collection, maintenance, and use/disclosure of that information. ",  
        homepage="https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa?spm=a3c0i.25996110.4926726760.2.4eb17508CeCvPA",  
    ),
    "dpp": ComplianceFramework(
        compliance_framework_id="dpp",
        name="DPP",
        abbreviation="DPP",
        description="The Digital Production Partnership (DPP) Committed to Security programme allows all production and broadcast suppliers to demonstrate their commitment to working towards and adhering to cyber security best practice.Alibaba Cloud has attained the DPP Security Marks for Production and Broadcast under the DPP’s 'Committed to Security’ program. The two new, globally recognized security marks from the DPP further expand Alibaba Cloud’s security and compliance footprint in the media and broadcasting industry.",  
        homepage="https://www.thedpp.com/security?spm=a3c0i.24097780.3130899490.1.2486480fA1V4es",  
    ),
    "fisc": ComplianceFramework(
        compliance_framework_id="fisc",
        name="FISC",
        abbreviation="FISC",
        description="The Center for Financial Industry Information Systems (FISC) was established in November 1984 with the approval of the Minister of the Finance. FISC has a broad membership, including financial institutions, insurance companies, securities firms, computer manufacturers, and information processing companies. The FISC conducts research in the field of financial information system issues on various topics such as technology, utilization, control, and threat/defense, paying attention to the current status, problems, and future prospects in Japan and abroad, and measures to achieve them.",  
        homepage="",  
    ),
    "gdpr": ComplianceFramework(
        compliance_framework_id="gdpr",
        name="GDPR",
        abbreviation="GDPR",
        description="he EU GDPR is a consolidated legal framework intend to ensure the protection of “fundamental rights and freedoms of natural persons and in particular their right to the protection of personal data”. It is a mandatory law requiring compliance with provisions that apply throughout the European Union to the business usage of personal data. It substituted the patchwork of existing regulations and frameworks and the 20-year-old Directive (95/46/EC)",  
        homepage="https://gdpr-info.eu/",  
    ),
    "eu-cloud-coc": ComplianceFramework(
        compliance_framework_id="eu-cloud-coc",
        name="EU Cloud COC",
        abbreviation="EU Cloud COC",
        description="Alibaba Cloud has been verified for its compliance with the EU Cloud Code of Conduct by SCOPE Europe, the independent monitoring body of the Code. This verification underscores the stringent measures Alibaba Cloud has put in place to align with the General Data Protection Regulation (GDPR) requirements, providing privacy assurance to its customers.",  
        homepage="https://eucoc.cloud/en/home?spm=a3c0i.241527.3899437370.2.49267fa9y0ljfi",  
    ),
    "pdpa": ComplianceFramework(
        compliance_framework_id="pdpa",
        name="PDPA",
        abbreviation="PDPA",
        description="The Personal Data Protection Commission (PDPC) regulates the personal data protection in Singapore. The Personal Data Protection Act (PDPA), passed by the Singapore Parliament on October 15, 2012, is the data protection law that comprises various rules governing the collection, use, disclosure and care of personal data.",  
        homepage="https://www.pdpc.gov.sg/",  
    ),
    "pdpo": ComplianceFramework(
        compliance_framework_id="pdpo",
        name="PDPO",
        abbreviation="PDPO",
        description="The data protection law in Hong Kong is the Personal Data (Privacy) Ordinance (Cap. 486). It came into force in 1996, a year after the European Data Protection Directive 95/46/EC, and it shares many of the base principles from the directive. The main objective is to protect the privacy rights of a person in relation to personal data (data subject). The Amendment Bill, relating to the regulation of the use of personal data for direct marketing purposes, was passed by the Legislative Council June 27, 2012. Here we shared our User Guide on Hong Kong Personal Data (Privacy) Ordinance (Cap. 486), to help our customers to learn more about the Ordinance and how does it compare to other privacy laws, such as the GDPR.",  
        homepage="https://www.pcpd.org.hk/english/data_privacy_law/ordinance_at_a_Glance/ordinance.html?spm=a3c0i.273588.9513437360.1.2e8d5313WNkzCJ",  
    ),
    "cbpr": ComplianceFramework(
        compliance_framework_id="cbpr",
        name="Global CBPR",
        abbreviation="Global CBPR",
        description="The Global Cross-Border Privacy Rules (CBPR) Forum’s privacy certifications, the Global CBPR and Global Privacy Recognition for Processors (PRP) System, are officially live as of June 2nd, 2025. The Global CBPR Framework (2023) includes nine guiding principles referencing the OECD’s Guidelines on the Protection of Privacy and Trans-Border Flows of Personal Data, and guidance to assist Global CBPR Forum Members in implementing the framework in domestic approaches to data protection and privacy, as well as forum-wide arrangements for interpreting its cross-border elements.",  
        homepage="https://www.globalcbpr.org/privacy-certifications/directory/?spm=a3c0i.23040130a3c0i.3130899490.1.43e45639nlq1Ek",  
    ),
    "prp": ComplianceFramework(
        compliance_framework_id="prp",
        name="Global PRP",
        abbreviation="Global PRP",
        description="The Global Cross-Border Privacy Rules (CBPR) Forum’s privacy certifications, the Global CBPR and Global Privacy Recognition for Processors (PRP) System, are officially live as of June 2nd, 2025. The Global CBPR Framework (2023) includes nine guiding principles referencing the OECD’s Guidelines on the Protection of Privacy and Trans-Border Flows of Personal Data, and guidance to assist Global CBPR Forum Members in implementing the framework in domestic approaches to data protection and privacy, as well as forum-wide arrangements for interpreting its cross-border elements.",  
        homepage="https://www.globalcbpr.org/privacy-certifications/directory/?spm=a3c0i.23040530.3130899490.1.3dda2956lDt6kM",  
    )


    # TODO add more e.g.
    # soc2t1
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


def _passmark(name: str, description: str, unit: str, higher_is_better: bool = True):
    measurement = sub(r"\W+", "_", name.lower())
    return Benchmark(
        benchmark_id="passmark:" + measurement,
        framework="passmark",
        measurement=measurement,
        name="PassMark: " + name,
        description=description,
        config_fields={
            "framework_version": "Version and build number of PassMark.",
        },
        unit=unit,
        higher_is_better=higher_is_better,
    )


benchmarks: List[Benchmark] = [
    Benchmark(
        benchmark_id="bogomips",
        name="BogoMips",
        description='A crude measurement of CPU speed by the Linux kernel. This is NOT usable for performance comparisons among different CPUs, but might be useful to check if a processor is in the range of similar processors. As often quoted, BogoMips measures "the number of million times per second a processor can do absolutely nothing".',
        framework="bogomips",
        unit="Millions of instructions per second (MIPS)",
    ),
    Benchmark(
        benchmark_id="bw_mem",
        name="Memory bandwidth",
        description="bw_mem allocates twice the specified amount of memory, zeros it, and then times the copying of the first half to the second half. Results are reported in megabytes moved per second (MB/sec). bw_mem is provided by lmbench. For more details, see the man pages.",
        framework="bw_mem",
        config_fields={
            "operation": "The type of measurement: 'rd' measures the time to read data into the processor, 'wr' measures the time to write data to memory, and 'rdwr' measures the time to read data into memory and then write data to the same memory location.",
            "size": "Amount of memory to be used in MB",
        },
        unit="Megabytes per second (MB/sec)",
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
        unit="Bytes per second (Bps)",
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
        unit="Bytes per second (Bps)",
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
        "Opens complex PDF documents (4 in single-core mode, 16 in multi-core mode) of park maps from the American National Park Service (sizes from 897 kB to 1.5 MB) with large vector images, lines and text.",
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
        "Separates and blurs the background of 10 frames in a 1080p video, using DeepLabV3+.",
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
        "Applies colour and blur filters, level adjustments, cropping, scaling, and image compositing filters to 10 photos range in size from 3 MP to 15 MP.",
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
        unit="Bytes per second (Bps)",
    ),
    Benchmark(
        benchmark_id="stress_ng:cpu_all",
        name="stress-ng CPU all",
        description="Stress the CPU with all available methods supported by stress-ng, and count the total bogo operations per second (in real time) based on wall clock run time. The stress methods include bit operations, recursive calculations, integer divisions, floating point operations, matrix multiplication, stats, trigonometric, and hash functions. Note that this is to be deprecated in favor of stress_ng:div16.",
        framework="stress_ng",
        measurement="cpu_all",
        config_fields={
            "cores": "Stressing a single core or all cores.",
            "framework_version": "Version number of stress-ng.",
        },
        unit="Bogo operations per second (ops/s)",
    ),
    Benchmark(
        benchmark_id="stress_ng:div16",
        name="stress-ng div16",
        description="Stress the CPU with the div16 method of stress-ng using a varying number of vCPU cores, and count the measured maximum total bogo operations per second (in real time) based on wall clock run time.",
        framework="stress_ng",
        measurement="div16",
        config_fields={
            "cores": "Number of CPU cores stressed.",
            "framework_version": "Version number of stress-ng.",
        },
        unit="Bogo operations per second (ops/s)",
    ),
    Benchmark(
        benchmark_id="stress_ng:best1",
        name="stress-ng div16 single-core",
        description="Stress a single vCPU core with the div16 method of stress-ng, and count the total bogo operations per second (in real time) based on wall clock run time.",
        framework="stress_ng",
        measurement="best1",
        config_fields={
            "framework_version": "Version number of stress-ng.",
        },
        unit="Bogo operations per second (ops/s)",
    ),
    Benchmark(
        benchmark_id="stress_ng:bestn",
        name="stress-ng div16 multi-core",
        description="Stress the CPU with the div16 method of stress-ng using a varying number of vCPU cores, and count the measured maximum total bogo operations per second (in real time) based on wall clock run time.",
        framework="stress_ng",
        measurement="bestn",
        config_fields={
            "framework_version": "Version number of stress-ng.",
        },
        unit="Bogo operations per second (ops/s)",
    ),
    Benchmark(
        benchmark_id="static_web:rps",
        name="Static web server+client speed",
        description="Serving smaller (1-65 kB) and larger (256-512 kB) files using a static HTTP server (binserve), and benchmarking each workload (wrk) using variable number of threads (and keeping the threads with the maximum performance) and connections (recorded after divided by the number of vCPUs to make it comparable with other servers with different vCPU count) on the same server. The measured RPS is not the maximum expected server speed, as the server shared CPU with the client.",
        framework="static_web",
        measurement="rps",
        config_fields={
            "size": "Served file size (kB).",
            "connections_per_vcpus": "Open HTTP connections per vCPU(s).",
            "framework_version": "Version number of both binserve and wrk.",
        },
        unit="Requests per second (rps)",
    ),
    Benchmark(
        benchmark_id="static_web:rps-extrapolated",
        name="Static web server (extrapolated) speed",
        description="Serving smaller (1-65 kB) and larger (256-512 kB) files using a static HTTP server (binserve), and benchmarking each workload (wrk) using variable number of threads (and keeping the threads with the maximum performance) and connections (recorded after divided by the number of vCPUs to make it comparable with other servers with different vCPU count) on the same server. The extrapolated RPS is based on the measured RPS adjusted by the server's and client's time spent executing in user/system mode, so trying to control for the client resource usage.",
        framework="static_web",
        measurement="rps-extrapolated",
        config_fields={
            "size": "Served file size (kB).",
            "connections_per_vcpus": "Open HTTP connections per vCPU(s).",
            "framework_version": "Version number of both binserve and wrk.",
        },
        unit="Requests per second (rps)",
    ),
    Benchmark(
        benchmark_id="static_web:throughput",
        name="Static web server+client throughput",
        description="Serving smaller (1-65 kB) and larger (256-512 kB) files using a static HTTP server (binserve), and benchmarking each workload (wrk) using variable number of threads (and keeping the threads with the maximum performance) and connections (recorded after divided by the number of vCPUs to make it comparable with other servers with different vCPU count) on the same server. Throughput is calculated by multiplying the RPS with the served file size. The measured RPS is not the maximum expected server speed, as the server shared CPU with the client.",
        framework="static_web",
        measurement="throughput",
        config_fields={
            "size": "Served file size (kB).",
            "connections_per_vcpus": "Open HTTP connections per vCPU(s).",
            "framework_version": "Version number of both binserve and wrk.",
        },
        unit="Bytes per second (Bps)",
    ),
    Benchmark(
        benchmark_id="static_web:throughput-extrapolated",
        name="Static web server (extrapolated) throughput",
        description="Serving smaller (1-65 kB) and larger (256-512 kB) files using a static HTTP server (binserve), and benchmarking each workload (wrk) using variable number of threads (and keeping the threads with the maximum performance) and connections (recorded after divided by the number of vCPUs to make it comparable with other servers with different vCPU count) on the same server. Extrapolated throughput is calculated by multiplying the exrapolated RPS with the served file size. The extrapolated RPS is based on the measured RPS adjusted by the server's and client's time spent executing in user/system mode, so trying to control for the client resource usage.",
        framework="static_web",
        measurement="throughput-extrapolated",
        config_fields={
            "size": "Served file size (kB).",
            "connections_per_vcpus": "Open HTTP connections per vCPU(s).",
            "framework_version": "Version number of both binserve and wrk.",
        },
        unit="Bytes per second (Bps)",
    ),
    Benchmark(
        benchmark_id="static_web:latency",
        name="Static web server latency",
        description="Serving smaller (1-65 kB) and larger (256-512 kB) files using a static HTTP server (binserve), and benchmarking each workload (wrk) using variable number of threads (and keeping the threads with the maximum performance) and connections (recorded after divided by the number of vCPUs to make it comparable with other servers with different vCPU count) on the same server. The average latency reported by wrk.",
        framework="static_web",
        measurement="latency",
        config_fields={
            "size": "Served file size (kB).",
            "connections_per_vcpus": "Open HTTP connections per vCPU(s).",
            "framework_version": "Version number of both binserve and wrk.",
        },
        unit="Seconds (sec)",
        higher_is_better=False,
    ),
    Benchmark(
        benchmark_id="redis:rps",
        name="Redis server+client speed",
        description="Running a pair of redis server and benchmarking client (memtier_benchmark) on each vCPU to evaluate the performance of SET operations, using different number of concurrent pipelined requests. The measured RPS (ops/sec) is the sum of RPS measured in all parallel processes, but is not the maximum expected redis server speed, as the server(s) shared CPU with the client(s).",
        framework="redis",
        measurement="rps",
        config_fields={
            "operation": "Type of operation, e.g. SET or GET a key.",
            "pipeline": "The number of concurrent pipelined requests.",
            "framework_version": "Redis server version number and build information.",
        },
        unit="Operations per second (ops/sec)",
    ),
    Benchmark(
        benchmark_id="redis:rps-extrapolated",
        name="Redis server (extrapolated) speed",
        description="Running a pair of redis server and benchmarking client (memtier_benchmark) on each vCPU to evaluate the performance of SET operations, using different number of concurrent pipelined requests. The extrapolated server speed is based on the measured speed adjusted by the server's and client's time spent executing in user/system mode, so trying to control for the client resource usage.",
        framework="redis",
        measurement="rps-extrapolated",
        config_fields={
            "operation": "Type of operation, e.g. SET or GET a key.",
            "pipeline": "The number of concurrent pipelined requests.",
            "framework_version": "Redis server version number and build information.",
        },
        unit="Operations per second (ops/sec)",
    ),
    Benchmark(
        benchmark_id="redis:latency",
        name="Redis latency",
        description="Running a pair of redis server and benchmarking client (memtier_benchmark) on each vCPU to evaluate the performance of SET operations, using different number of concurrent pipelined requests. The average latency reported by memtier_benchmark.",
        framework="redis",
        measurement="latency",
        config_fields={
            "operation": "Type of operation, e.g. SET or GET a key.",
            "pipeline": "The number of concurrent pipelined requests.",
            "framework_version": "Redis server version number and build information.",
        },
        unit="Milliseconds (ms)",
        higher_is_better=False,
    ),
    # https://www.cpubenchmark.net/cpu_test_info.html
    _passmark(
        name="CPU Mark",
        description="A composite average of the Integer, Floating point, Prime and String Sorting test scores, which can be used to compare CPUs from different platforms (even e.g. desktop vs mobile).",
        unit=None,
    ),
    _passmark(
        name="CPU Integer Maths Test",
        description="Testing how fast the CPU can perform mathematical integer operations, using large sets of an equal number of random 32-bit and 64-bit integers for addition, subtraction, multiplication and division, with integer buffers totaling about 240kb per core.",
        unit="Millions of operations per second (Mops/s)",
    ),
    _passmark(
        name="CPU Floating Point Maths Test",
        description="Testing how fast the CPU can perform mathematical floating point operations, using large sets of an equal number of random 32-bit and 64-bit floating point numbers for addition (30% of the time), subtraction (30% of the time), multiplication (30% of the time) and division (10% of the time), with floating point buffers totaling about 240kb per core.",
        unit="Millions of operations per second (Mops/s)",
    ),
    _passmark(
        name="CPU Prime Numbers Test",
        description="Finding prime numbers using the Sieve of Atkin formula (with a limit of 32 million) on 64-bit integers with 4MB of memory per thread.",
        unit="Million prime numbers per second (Mnums/s)",
    ),
    _passmark(
        name="CPU String Sorting Test",
        description="Sorting strings using the Quicksort algorithm with memory buffers totaling about 25MB per core.",
        unit="Thousands of strings per second (Kstrings/s)",
    ),
    _passmark(
        name="CPU Encryption Test",
        description="Encrypting blocks of random data using AES, SHA256 and ECDSA with any available specialized CPU instruction sets and memory buffers totaling about 1MB per core.",
        unit="Megabytes per second (MB/s)",
    ),
    _passmark(
        name="CPU Compression Test",
        description="Using Gzip (Crypto++ 8.6) to compress blocks of data with a 4MB memory buffer size per core.",
        unit="Kilobytes per second (kB/s)",
    ),
    _passmark(
        name="CPU Single Threaded Test",
        description="Using a single logical core for a mixture of floating point, string sorting and data compression tests.",
        unit="Millions of operations per second (Mops/s)",
    ),
    _passmark(
        name="CPU Physics Test",
        description="Simulating the same physics interactions as many times as possible within a timeframe, using the Bullet Physics Engine (version 2.88 for x86, 3.07 for ARM).",
        unit="Frames per second (fps)",
    ),
    _passmark(
        name="CPU Extended Instructions Test",
        description="Testing how fast the CPU can perform mathematical operations using extended instructions, such as SSE, FMA, AVX, AVX512 and NEON.",
        unit="Millions of matrices per second (Mmat/s)",
    ),
    # https://forums.passmark.com/performancetest/4599-formula-cpu-mark-memory-mark-and-disk-mark?p=54964#post54964
    _passmark(
        name="Memory Mark",
        description="A composite score of PassMark's Database and Memory test cases",
        unit=None,
    ),
    _passmark(
        name="Database Operations",
        # https://www.databasebenchmarks.net/chart-notes.html
        description="Single threaded and multi-threaded CRUD operations, such as INSERT (40%), SELECT (26%), UPDATE (24%), and DELETE (10%) on a relational database with 4 tables and 1k rows per table.",
        unit="Thousands of operations per second (Kops/s)",
    ),
    # https://www.memorybenchmark.net/graph_notes.html
    _passmark(
        name="Memory Read Cached",
        description="Read a combination of 32-bit and 64-bit data from memory.",
        unit="Megabytes per second (MB/s)",
    ),
    _passmark(
        name="Memory Read Uncached",
        description="Read a combination of 32-bit and 64-bit data from memory using a 512 MB block size.",
        unit="Megabytes per second (MB/s)",
    ),
    _passmark(
        name="Memory Write",
        description="Write a combination of 32-bit and 64-bit data to the memory using a 512 MB block size.",
        unit="Megabytes per second (MB/s)",
    ),
    _passmark(
        name="Memory Latency",
        description="Measuring the time it takes for a single byte of memory to be transferred to the CPU for processing. A 512 MB buffer is allocated and then filled with pointers to other locations in the buffer, looping through a linked list.",
        unit="Nanoseconds (ns)",
        higher_is_better=False,
    ),
    Benchmark(
        benchmark_id="llm_speed:text_generation",
        name="LLM inference speed for text generation",
        description="Running llama-bench from llama.cpp using various quantized model files to measure the speed of generating 16 to 4k tokens.",
        framework="llm_speed",
        measurement="text_generation",
        config_fields={
            "model": "Name of the model file used.",
            "tokens": "Number of tokens processed in one run.",
            "framework_version": "Git commit hash of llama.cpp",
        },
        unit="tokens/second (t/s)",
    ),
    Benchmark(
        benchmark_id="llm_speed:prompt_processing",
        name="LLM inference speed for prompt processing",
        description="Running llama-bench from llama.cpp using various quantized model files to measure the speed of processing 16 to 16k tokens.",
        framework="llm_speed",
        measurement="prompt_processing",
        config_fields={
            "model": "Name of the model file used.",
            "tokens": "Number of tokens processed in one run.",
            "framework_version": "Git commit hash of llama.cpp",
        },
        unit="tokens/second (t/s)",
    ),
]
