from sqlmodel import Field, SQLModel


class Country(SQLModel, table=True):
    id: str = Field(default=None, primary_key=True)
    continent: str


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


countries = {
    k: Country(id=k, continent=v) for k, v in country_continent_mapping.items()
}
