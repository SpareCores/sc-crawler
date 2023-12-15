"""Helpers to work with physical addresses."""


class Location:
    """Structured physical address reference including continent, country etc.

    Examples:
        >>> Location('Europe', 'United Kingdom', 'England', 'London', '221B Baker Street', '', 'NW1 6XE')
        Location('Europe', 'United Kingdom', 'England', 'London', '221B Baker Street', '', 'NW1 6XE')
    """

    def __init__(self,
                 continent: str, country: str, state: str, city: str,
                 address_line1: str, address_line2: str, zip_code: str):
        self.continent = continent # TODO drop? should be evident from the country .. lookup
        self.country = country
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

