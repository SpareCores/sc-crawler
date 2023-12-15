"""Helpers to work with physical addresses."""


from Countrydetails import country, countries


class Location:
    """Structured physical address reference including continent, country etc.

    Examples:
        >>> Location('United Kingdom', 'England', 'London', '221B Baker Street', '', 'NW1 6XE')
        Location('United Kingdom', 'England', 'London', '221B Baker Street', '', 'NW1 6XE')
    """

    def __init__(self,
                 country: str, state: str, city: str,
                 address_line1: str, address_line2: str, zip_code: str):
        if country not in countries.all_countries().countries():
            raise LookupError('Unknown country')
        self.country = country
        self.continent = country.country_details(country_name = country).continent()
        self.state = state
        self.city = city
        self.address_line1 = address_line1
        self.address_line2 = address_line2
        self.zip_code = zip_code

    def get_continent(self):
        return self.continent

    def get_country(self):
        return self.country

    def get_state(self):
        return self.state

    def get_city(self, city):
        return self.city

    def get_address_line1(self):
        return self.address_line1

    def get_address_line2(self):
        return self.address_line2

    def get_zip_code(self):
        return self.zip_code

    def __str__(self):
        address = self.address_line1
        if self.address_line2:
            address += ' ' + self.address_line2
        address += '\n' + self.city + ' ' + self.state + ' ' + self.zip_code
        address += '\n' + self.country
        return address
