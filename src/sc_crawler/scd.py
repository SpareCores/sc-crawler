from datetime import datetime
from typing import List

from sqlmodel import Field, SQLModel

from .schemas import ScModel, CountryBase, is_table


class Scd(ScModel):
    """Override the `observed_at` column to be primary key in SCD tables."""

    observed_at: datetime = Field(
        primary_key=True,
        default_factory=datetime.utcnow,
        sa_column_kwargs={"onupdate": datetime.utcnow},
        description="Timestamp of the last observation.",
    )


class CountryScd(Scd, CountryBase, table=True):
    pass


scd_tables: List[SQLModel] = [o for o in globals().values() if is_table(o)]
"""List of all SCD SQLModel (table) models."""
