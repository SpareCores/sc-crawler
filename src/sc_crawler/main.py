from .models import db_session, Datacenter, Vendor


def app():
    with db_session()() as session:
        session.add_all(
            [
                Vendor(id="aws", name="Amazon Web Services"),
                Datacenter(id="us-east-1a", vendor_id="aws", name="US East"),
            ]
        )
        session.commit()


def query_dc():
    with db_session()() as session:
        r = session.query(Datacenter).filter(Datacenter.vendor_id == "aws")
        for dc in r.all():
            print(dc.id, dc.name)


if __name__ == "__main__":
    app()

