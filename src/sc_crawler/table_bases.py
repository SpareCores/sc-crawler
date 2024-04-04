"""Tiny helper classes for the most commonly used fields to be inherited by [sc_crawler.tables][]."""

from datetime import datetime
from hashlib import sha1
from json import dumps
from typing import List, Optional, Union

from rich.progress import Progress
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import declared_attr
from sqlmodel import JSON, Field, Session, SQLModel, select

from .str_utils import snake_case
from .table_fields import (
    Allocation,
    Cpu,
    CpuAllocation,
    CpuArchitecture,
    Disk,
    Gpu,
    PriceTier,
    PriceUnit,
    Status,
    StorageType,
    TrafficDirection,
)


class ScMetaModel(SQLModel.__class__):
    """Custom class factory to auto-update table models.

    - Reuse description of the table and its fields as SQL comment.

        Checking if the table and its fields have explicit comment set
        to be shown in the `CREATE TABLE` statements, and if not,
        reuse the optional table and field descriptions. Table
        docstrings are truncated to first line.

    - Reuse description of the fields to dynamically append to the
        docstring in the Attributes section.

    - Set `__validator__` to the parent Pydantic model without
        `table=True`, which is useful for running validations.
        The Pydantic model is found by the parent class' name ending in "Base".

    - Auto-generate SCD table docs from the non-SCD table docs.
    """

    def __init__(subclass, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # early return for non-tables
        if subclass.model_config.get("table") is None:
            return
        satable = subclass.metadata.tables[subclass.__tablename__]

        # table comment
        if subclass.__doc__ and satable.comment is None:
            satable.comment = subclass.__doc__.splitlines()[0]

        # column comments
        for k, v in subclass.model_fields.items():
            comment = satable.columns[k].comment
            if v.description and comment is None:
                satable.columns[k].comment = v.description

        # generate docstring for SCD tables
        if subclass.__name__.endswith("Scd"):
            from .tables import tables

            nonscd = [t for t in tables if t.__name__ == subclass.__name__[:-3]][0]
            doclines = nonscd.__doc__.splitlines()
            # drop trailing dot and append SCD
            doclines[0] = doclines[0][:-1] + " (SCD Type 2)."
            subclass.__doc__ = "\n".join(doclines)
        else:
            # describe table columns as attributes in docstring
            subclass.__doc__ = subclass.__doc__ + "\n\nAttributes:\n"
            for k, v in subclass.model_fields.items():
                if not hasattr(v.annotation, "__args__"):
                    typehint = v.annotation.__name__
                else:
                    typehint = str(v.annotation)
                description = satable.columns[k].comment
                subclass.__doc__ = (
                    subclass.__doc__ + f"    {k} ({typehint}): {description}\n"
                )

        # find Pydantic model parent to be used for validating
        subclass.__validator__ = [
            m for m in subclass.__bases__ if m.__name__.endswith("Base")
        ][0]


class ScModel(SQLModel, metaclass=ScMetaModel):
    """Custom extensions to SQLModel objects and tables.

    Extra features:

    - auto-generated table names using [snake_case][sc_crawler.str_utils.snake_case],
    - support for hashing table rows,
    - reuse description field of tables/columns as SQL comment,
    - reuse description field of columns to extend the `Attributes` section of the docstring.
    """

    @declared_attr  # type: ignore
    def __tablename__(cls) -> str:
        """Override tables names using all-lowercase [snake_case][sc_crawler.str_utils.snake_case]."""
        return snake_case(cls.__name__)

    @classmethod
    def get_columns(cls) -> List[str]:
        """Return the table's column names in a dict for all, primary keys, and attributes."""
        columns = cls.__table__.columns.keys()
        pks = [pk.name for pk in inspect(cls).primary_key]
        attributes = [a for a in columns if a not in set(pks)]
        return {"all": columns, "primary_keys": pks, "attributes": attributes}

    @classmethod
    def get_table_name(cls) -> str:
        """Return the SQLModel object's table name."""
        return str(cls.__tablename__)

    @classmethod
    def get_validator(cls) -> Union["ScModel", None]:
        """Return the parent Base Pydantic model (without a table definition)."""
        if cls.model_config.get("table") is None:
            return None
        return cls.__validator__

    @classmethod
    def get_scd(cls) -> Union["ScModel", None]:
        """Return the SCD version of the SQLModel table."""
        if cls.model_config.get("table") is None:
            return None
        from .tables_scd import tables_scd

        validator = cls.get_validator()
        scds = [t for t in tables_scd if t.get_validator() == validator]
        if len(scds) != 1:
            raise ValueError("Not found SCD definition.")
        return scds[0]

    @classmethod
    def hash(
        cls,
        session: Session,
        ignored: List[str] = ["observed_at"],
        progress: Optional[Progress] = None,
    ) -> dict:
        """Hash the content of the rows.

        Args:
            session: Database connection to use for object lookups.
            ignored: List of column names to exclude from hashing.
            progress: Optional progress bar to track the status of the hashing.

        Returns:
            Dictionary of the row hashes keyed by the JSON dump of primary keys.
        """
        pks = sorted(cls.get_columns()["primary_keys"])
        rows = session.exec(statement=select(cls))
        if progress:
            table_task_id = progress.add_task(
                cls.get_table_name(),
                total=session.query(cls).count(),
            )
        # no use of a generator as will need to serialize to JSON anyway
        hashes = {}
        for row in rows:
            # NOTE Pydantic is warning when read Gpu/Storage as dict
            # https://github.com/tiangolo/sqlmodel/issues/63#issuecomment-1081555082
            rowdict = row.model_dump(warnings=False)
            keys = {pk: rowdict.get(pk) for pk in pks}
            keys_id = dumps(keys, sort_keys=True)
            for dropkey in [*ignored, *pks]:
                rowdict.pop(dropkey, None)
            rowhash = sha1(dumps(rowdict, sort_keys=True).encode()).hexdigest()
            hashes[keys_id] = rowhash
            if progress:
                progress.update(table_task_id, advance=1)

        return hashes


class MetaColumns(ScModel):
    """Helper class to add the `status` and `observed_at` columns."""

    status: Status = Field(
        default=Status.ACTIVE,
        description="Status of the resource (active or inactive).",
    )
    observed_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        description="Timestamp of the last observation.",
    )


class HasComplianceFrameworkIdPK(ScModel):
    compliance_framework_id: str = Field(
        primary_key=True, description="Unique identifier."
    )


class HasVendorIdPK(ScModel):
    vendor_id: str = Field(primary_key=True, description="Unique identifier.")


class HasDatacenterIdPK(ScModel):
    datacenter_id: str = Field(
        primary_key=True, description="Unique identifier, as called at the Vendor."
    )


class HasZoneIdPK(ScModel):
    zone_id: str = Field(
        primary_key=True, description="Unique identifier, as called at the Vendor."
    )


class HasStorageIdPK(ScModel):
    storage_id: str = Field(
        primary_key=True, description="Unique identifier, as called at the Vendor."
    )


class HasServerIdPK(ScModel):
    server_id: str = Field(
        primary_key=True, description="Unique identifier, as called at the Vendor."
    )


class HasName(ScModel):
    name: str = Field(description="Human-friendly name.")


class HasDescription(ScModel):
    description: Optional[str] = Field(description="Short description.")


class HasVendorPKFK(ScModel):
    vendor_id: str = Field(
        foreign_key="vendor",
        primary_key=True,
        description="Reference to the Vendor.",
    )


class HasDatacenterPK(ScModel):
    datacenter_id: str = Field(
        primary_key=True,
        description="Reference to the Datacenter.",
    )


class HasZonePK(ScModel):
    zone_id: str = Field(primary_key=True, description="Reference to the Zone.")


class HasServerPK(ScModel):
    server_id: str = Field(
        primary_key=True,
        description="Reference to the Server.",
    )


class HasStoragePK(ScModel):
    storage_id: str = Field(
        primary_key=True,
        description="Reference to the Storage.",
    )


class HasPriceFieldsBase(ScModel):
    unit: PriceUnit = Field(description="Billing unit of the pricing model.")
    # set to max price if tiered
    price: float = Field(description="Actual price of a billing unit.")
    # e.g. setup fee for dedicated servers,
    # or upfront costs of a reserved instance type
    price_upfront: float = Field(
        default=0, description="Price to be paid when setting up the resource."
    )
    price_tiered: List[PriceTier] = Field(
        default=[],
        sa_type=JSON,
        description="List of pricing tiers with min/max thresholds and actual prices.",
    )
    currency: str = Field(default="USD", description="Currency of the prices.")


class HasPriceFields(MetaColumns, HasPriceFieldsBase):
    pass


class CountryFields(ScModel):
    country_id: str = Field(
        primary_key=True,
        description="Country code by ISO 3166 alpha-2.",
    )
    continent: str = Field(description="Continent name.")


class CountryBase(MetaColumns, CountryFields):
    pass


class ComplianceFrameworkFields(ScModel):
    abbreviation: Optional[str] = Field(
        description="Short abbreviation of the Framework name."
    )
    description: Optional[str] = Field(
        description=(
            "Description of the framework in a few paragrahs, "
            "outlining key features and characteristics for reference."
        )
    )
    logo: Optional[str] = Field(
        default=None,
        description="Publicly accessible URL to the image of the Framework's logo.",
    )
    homepage: Optional[str] = Field(
        default=None,
        description="Public homepage with more information on the Framework.",
    )


class ComplianceFrameworkBase(
    MetaColumns, ComplianceFrameworkFields, HasName, HasComplianceFrameworkIdPK
):
    pass


class VendorFields(HasName, HasVendorIdPK):
    logo: Optional[str] = Field(
        default=None,
        description="Publicly accessible URL to the image of the Vendor's logo.",
    )
    homepage: Optional[str] = Field(
        default=None,
        description="Public homepage of the Vendor.",
    )

    country_id: str = Field(
        foreign_key="country",
        description="Reference to the Country, where the Vendor's main headquarter is located.",
    )
    state: Optional[str] = Field(
        default=None,
        description="Optional state/administrative area of the Vendor's location within the Country.",
    )
    city: Optional[str] = Field(
        default=None, description="Optional city name of the Vendor's main location."
    )
    address_line: Optional[str] = Field(
        default=None, description="Optional address line of the Vendor's main location."
    )
    zip_code: Optional[str] = Field(
        default=None, description="Optional ZIP code of the Vendor's main location."
    )

    # https://dbpedia.org/ontology/Organisation
    founding_year: int = Field(description="4-digit year when the Vendor was founded.")

    status_page: Optional[str] = Field(
        default=None,
        description="Public status page of the Vendor.",
    )


class VendorBase(MetaColumns, VendorFields):
    pass


class VendorComplianceLinkFields(HasVendorPKFK):
    compliance_framework_id: str = Field(
        foreign_key="compliance_framework",
        primary_key=True,
        description="Reference to the Compliance Framework.",
    )
    comment: Optional[str] = Field(
        default=None,
        description="Optional references, such as dates, URLs, and additional information/evidence.",
    )


class VendorComplianceLinkBase(MetaColumns, VendorComplianceLinkFields):
    pass


class DatacenterFields(HasName, HasDatacenterIdPK, HasVendorPKFK):
    aliases: List[str] = Field(
        default=[],
        sa_type=JSON,
        description="List of other commonly used names for the same Datacenter.",
    )
    country_id: str = Field(
        foreign_key="country",
        description="Reference to the Country, where the Datacenter is located.",
    )
    state: Optional[str] = Field(
        default=None,
        description="Optional state/administrative area of the Datacenter's location within the Country.",
    )
    city: Optional[str] = Field(
        default=None, description="Optional city name of the Datacenter's location."
    )
    address_line: Optional[str] = Field(
        default=None, description="Optional address line of the Datacenter's location."
    )
    zip_code: Optional[str] = Field(
        default=None, description="Optional ZIP code of the Datacenter's location."
    )

    founding_year: Optional[int] = Field(
        default=None, description="4-digit year when the Datacenter was founded."
    )
    green_energy: Optional[bool] = Field(
        default=None,
        description="If the Datacenter is 100% powered by renewable energy.",
    )


class DatacenterBase(MetaColumns, DatacenterFields):
    pass


class ZoneBase(MetaColumns, HasName, HasZoneIdPK, HasDatacenterPK, HasVendorPKFK):
    pass


class StorageFields(HasDescription, HasName, HasStorageIdPK, HasVendorPKFK):
    storage_type: StorageType = Field(
        description="High-level category of the storage, e.g. HDD or SDD."
    )
    max_iops: Optional[int] = Field(
        default=None, description="Maximum Input/Output Operations Per Second."
    )
    max_throughput: Optional[int] = Field(
        default=None, description="Maximum Throughput (MiB/s)."
    )
    min_size: Optional[int] = Field(
        default=None, description="Minimum required size (GiB)."
    )
    max_size: Optional[int] = Field(
        default=None, description="Maximum possible size (GiB)."
    )


class StorageBase(MetaColumns, StorageFields):
    pass


class ServerFields(HasServerIdPK, HasVendorPKFK):
    name: str = Field(
        default=None,
        description="Human-friendly name or short description.",
    )
    vcpus: int = Field(
        default=None,
        description="Default number of virtual CPUs (vCPU) of the server.",
    )
    hypervisor: Optional[str] = Field(
        default=None,
        description="Hypervisor of the virtual server, e.g. Xen, KVM, Nitro or Dedicated.",
    )
    cpu_allocation: CpuAllocation = Field(
        default=None,
        description="Allocation of CPU(s) to the server, e.g. shared, burstable or dedicated.",
    )
    cpu_cores: int = Field(
        default=None,
        description=(
            "Default number of CPU cores of the server. "
            "Equals to vCPUs when HyperThreading is disabled."
        ),
    )
    cpu_speed: Optional[float] = Field(
        default=None, description="Vendor-reported maximum CPU clock speed (GHz)."
    )
    cpu_architecture: CpuArchitecture = Field(
        default=None,
        description="CPU architecture (arm64, arm64_mac, i386, or x86_64).",
    )
    cpu_manufacturer: Optional[str] = Field(
        default=None,
        description="The manufacturer of the primary processor, e.g. Intel or AMD.",
    )
    cpu_family: Optional[str] = Field(
        default=None,
        description="The product line/family of the primary processor, e.g. Xeon, Core i7, Ryzen 9.",
    )
    cpu_model: Optional[str] = Field(
        default=None,
        description="The model number of the primary processor, e.g. 9750H.",
    )
    cpus: List[Cpu] = Field(
        default=[],
        sa_type=JSON,
        description=(
            "JSON array of known CPU details, e.g. the manufacturer, family, model; "
            "L1/L2/L3 cache size; microcode version; feature flags; bugs etc."
        ),
    )
    memory: int = Field(
        default=None,
        description="RAM amount (MiB).",
    )
    gpu_count: int = Field(
        default=0,
        description="Number of GPU accelerator(s).",
    )
    gpu_memory_min: Optional[int] = Field(
        default=None,
        description="Memory (MiB) allocated to the lowest-end GPU accelerator.",
    )
    gpu_memory_total: Optional[int] = Field(
        default=None,
        description="Overall memory (MiB) allocated to all the GPU accelerator(s).",
    )
    gpu_manufacturer: Optional[str] = Field(
        default=None,
        description="The manufacturer of the primary GPU accelerator, e.g. Nvidia or AMD",
    )
    gpu_model: Optional[str] = Field(
        default=None,
        description="The model number of the primary GPU accelerator.",
    )
    gpus: List[Gpu] = Field(
        default=[],
        sa_type=JSON,
        description=(
            "JSON array of GPU accelerator details, including "
            "the manufacturer, name, and memory (MiB) of each GPU."
        ),
    )
    storage_size: int = Field(
        default=0,
        description="Overall size (GB) of the disk(s).",
    )
    storage_type: Optional[StorageType] = Field(
        default=None,
        description="Primary disk type, e.g. HDD, SSD, NVMe SSD, or network).",
    )
    storages: List[Disk] = Field(
        default=[],
        sa_type=JSON,
        description=(
            "JSON array of disks attached to the server, including "
            "the size (MiB) and type of each disk."
        ),
    )
    network_speed: Optional[float] = Field(
        default=None,
        description="The baseline network performance (Gbps) of the network card.",
    )
    inbound_traffic: float = Field(
        default=0,
        description="Amount of complimentary inbound traffic (GB) per month.",
    )
    outbound_traffic: float = Field(
        default=0,
        description="Amount of complimentary outbound traffic (GB) per month.",
    )
    ipv4: int = Field(
        default=0, description="Number of complimentary IPv4 address(es)."
    )


class ServerBase(MetaColumns, ServerFields):
    pass


class ServerPriceFields(ScModel):
    operating_system: str = Field(description="Operating System.")
    allocation: Allocation = Field(
        default=Allocation.ONDEMAND,
        description="Allocation method, e.g. on-demand or spot.",
        primary_key=True,
    )


class ServerPriceBase(
    HasPriceFields,
    ServerPriceFields,
    HasServerPK,
    HasZonePK,
    HasDatacenterPK,
    HasVendorPKFK,
):
    pass


class StoragePriceBase(HasPriceFields, HasStoragePK, HasDatacenterPK, HasVendorPKFK):
    pass


class TrafficPriceFields(HasDatacenterPK, HasVendorPKFK):
    direction: TrafficDirection = Field(
        description="Direction of the traffic: inbound or outbound.",
        primary_key=True,
    )


class TrafficPriceBase(HasPriceFields, TrafficPriceFields):
    pass


class Ipv4PriceBase(HasPriceFields, HasDatacenterPK, HasVendorPKFK):
    pass
