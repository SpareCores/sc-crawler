from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel import Session, create_engine
from typer.testing import CliRunner

from sc_crawler.cli import cli
from sc_crawler.table_fields import CpuAllocation, CpuArchitecture, Status
from sc_crawler.tables import Country, Database, Server
from sc_crawler.utils import create_sc_engine
from sc_crawler.vendor_helpers import (
    retirement_date_from_rules,
    status_from_retirement_date,
)
from sc_crawler.vendors import vendors
from sc_crawler.vendors._alicloud import _ALICLOUD_RETIREMENT_RULES
from sc_crawler.vendors._aws import _AWS_EC2_RETIREMENT_RULES, _AWS_RDS_RETIREMENT_RULES
from sc_crawler.vendors._azure import _azure_sku_retirement_date
from sc_crawler.vendors._gcp import _gcp_machine_type_retirement_date
from sc_crawler.vendors._ovh import _database_end_of_sale

runner = CliRunner()


def test_status_from_retirement_date():
    assert status_from_retirement_date(None) == Status.ACTIVE
    retirement_date = date(2027, 1, 1)
    assert (
        status_from_retirement_date(retirement_date, as_of=date(2026, 12, 31))
        == Status.PLANNED_FOR_RETIREMENT
    )
    for as_of in (date(2027, 1, 1), date(2027, 1, 2)):
        assert status_from_retirement_date(retirement_date, as_of) == Status.RETIRED


@pytest.mark.parametrize(
    "rules, name, expected",
    [
        (_AWS_EC2_RETIREMENT_RULES, "u-9tb1.112xlarge", date(2025, 6, 20)),
        (_AWS_EC2_RETIREMENT_RULES, "u-24tb1.metal", date(2025, 6, 20)),
        (_AWS_EC2_RETIREMENT_RULES, "u-6tb1.112xlarge", None),
        (_AWS_EC2_RETIREMENT_RULES, "u7i-12tb.224xlarge", None),
        (_AWS_RDS_RETIREMENT_RULES, "db.m3.large", date(2023, 2, 1)),
        (_AWS_RDS_RETIREMENT_RULES, "db.r3.xlarge", date(2023, 2, 1)),
        (_AWS_RDS_RETIREMENT_RULES, "db.t2.micro", date(2024, 12, 31)),
        (_AWS_RDS_RETIREMENT_RULES, "db.m4.large", date(2024, 12, 31)),
        (_AWS_RDS_RETIREMENT_RULES, "db.m5.large", None),
        (_AWS_RDS_RETIREMENT_RULES, "db.r4g.large", None),
        (_ALICLOUD_RETIREMENT_RULES, "ecs.gn4.c4g1.xlarge", date(2026, 10, 1)),
        (_ALICLOUD_RETIREMENT_RULES, "ecs.sgn6i-vws.xlarge", date(2026, 10, 1)),
        (_ALICLOUD_RETIREMENT_RULES, "ecs.gn6i-c4g1.xlarge", None),
        (_ALICLOUD_RETIREMENT_RULES, "ecs.ebmc4.8xlarge", date(2026, 9, 15)),
        (_ALICLOUD_RETIREMENT_RULES, "ecs.ebmc4.16xlarge", None),
    ],
)
def test_retirement_date_from_rules(rules, name, expected):
    assert retirement_date_from_rules(name, rules) == expected


def test_azure_sku_retirement_date():
    api_dates = {"Standard_GS5": date(2028, 6, 1)}
    with patch(
        "sc_crawler.vendors._azure._vm_retirement_dates", return_value=api_dates
    ):
        # from the API, then from _AZURE_RETIREMENT_RULES
        assert _azure_sku_retirement_date("Standard_GS5") == date(2028, 6, 1)
        assert _azure_sku_retirement_date("Standard_D2_v3") == date(2029, 11, 15)
        assert _azure_sku_retirement_date("Standard_D2s_v5") is None


def test_gcp_machine_type_retirement_date_prefers_deleted():
    def _deprecated(obsolete="", deleted=""):
        return SimpleNamespace(obsolete=obsolete, deleted=deleted)

    assert _gcp_machine_type_retirement_date(_deprecated()) is None
    assert _gcp_machine_type_retirement_date(
        _deprecated(obsolete="2027-01-01T00:00:00-08:00")
    ) == date(2027, 1, 1)
    assert _gcp_machine_type_retirement_date(
        _deprecated(
            obsolete="2027-01-01T00:00:00-08:00", deleted="2027-03-01T00:00:00Z"
        )
    ) == date(2027, 3, 1)
    # the UTC date: 20:00 in UTC-8 is already the next day in UTC
    assert _gcp_machine_type_retirement_date(
        _deprecated(obsolete="2027-01-01T20:00:00-08:00")
    ) == date(2027, 1, 2)
    # no offset: taken as UTC
    assert _gcp_machine_type_retirement_date(
        _deprecated(obsolete="2027-01-01T23:00:00")
    ) == date(2027, 1, 1)


def test_ovh_database_end_of_sale_is_the_earliest_of_plan_and_flavor():
    assert _database_end_of_sale(None, {"status": "STABLE"}) is None
    assert _database_end_of_sale(
        {"endOfSale": "2027-05-12"}, {"endOfSale": None}
    ) == date(2027, 5, 12)
    assert _database_end_of_sale(
        {"endOfSale": "2027-05-12"}, {"endOfSale": "2027-01-31"}
    ) == date(2027, 1, 31)


def test_retirement_date_migration_keeps_the_rows(tmp_path):
    """Down- and upgrade of 67f053fde65f with data: rows and values are kept."""
    connection_string = f"sqlite:///{tmp_path / 'db.sqlite'}"
    schemas = ["schemas", "--connection-string", connection_string]

    def migrate(command, revision=None):
        args = ["schemas", command, *schemas[1:]]
        if revision:
            args += ["--revision", revision]
        result = runner.invoke(cli, args)
        assert result.exit_code == 0, result.output

    migrate("upgrade")
    common = dict(
        vendor_id="hcloud",
        api_reference="x",
        display_name="x",
        description="x",
        status=Status.PLANNED_FOR_RETIREMENT,
        retirement_date=date(2027, 1, 1),
    )
    with Session(create_sc_engine(connection_string)) as session:
        session.add(Country(country_id="DE", continent="Europe"))
        session.merge(vendors.hcloud.model_copy())
        session.add(
            Server(
                server_id="cx22",
                name="cx22",
                vcpus=2,
                memory_amount=4096,
                cpu_allocation=CpuAllocation.SHARED,
                cpu_architecture=CpuArchitecture.X86_64,
                **common,
            )
        )
        session.add(Database(database_id="db-2", name="db-2", **common))
        session.commit()

    def rows(conn):
        return (
            conn.exec_driver_sql(
                "SELECT server_id, name, vcpus, memory_amount, status FROM server"
            ).all(),
            conn.exec_driver_sql(
                "SELECT database_id, name, status FROM database"
            ).all(),
        )

    expected = (
        [("cx22", "cx22", 2, 4096, "PLANNED_FOR_RETIREMENT")],
        [("db-2", "db-2", "PLANNED_FOR_RETIREMENT")],
    )
    migrate("downgrade", "64c7aace12bf")
    with create_engine(connection_string).connect() as conn:
        assert rows(conn) == expected
        for table in ("server", "database"):
            columns = [
                c[1] for c in conn.exec_driver_sql(f"PRAGMA table_info({table})")
            ]
            assert "retirement_date" not in columns
    migrate("upgrade")
    with create_engine(connection_string).connect() as conn:
        assert rows(conn) == expected
        # the date is lost by the downgrade, back as NULL
        assert conn.exec_driver_sql(
            "SELECT retirement_date FROM server UNION ALL "
            "SELECT retirement_date FROM database"
        ).all() == [(None,), (None,)]
