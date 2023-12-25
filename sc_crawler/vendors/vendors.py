from .. import Location, Vendor

aws = Vendor(
    identifier='aws',
    name='Amazon Web Services',
    homepage='https://aws.amazon.com',
    location=Location(
        country='US',
        city='Seattle',
        address_line1='410 Terry Ave N'
    ),
    found_date=2002,
)
