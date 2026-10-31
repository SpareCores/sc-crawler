from datetime import UTC, datetime

from sc_crawler_audit.compare import compare_vendor
from sc_crawler_audit.export import Ours, sku_keys
from sc_crawler_audit.parsers import _aws_network, _aws_storage
from sc_crawler_audit.schema import Extraction, SourcePage, VendorSources
from sc_crawler_audit.sources import extracted_dir, is_allowed, page_slug


def _server(server_id, vcpus, memory_mib, status="ACTIVE", **kwargs):
    return {
        "server_id": server_id,
        "name": server_id,
        "api_reference": server_id,
        "display_name": server_id,
        "family": None,
        "series": None,
        "status": status,
        "vcpus": vcpus,
        "cpu_manufacturer": None,
        "cpu_family": None,
        "cpu_model": None,
        "cpu_speed": None,
        "cpu_allocation": None,
        "memory_amount": memory_mib,
        "accelerator_count": 0,
        "accelerator_model": None,
        "accelerator_memory_total": 0,
        "storage_size": 40,
        "storage_type": "NVME_SSD",
        "network_speed_baseline": None,
        "network_speed_max": None,
        **kwargs,
    }


def _price(server_id, region_id, price, allocation="ONDEMAND", currency="EUR"):
    return {
        "server_id": server_id,
        "region_id": region_id,
        "zone_id": region_id,
        "operating_system": "Linux",
        "allocation": allocation,
        "unit": "HOUR",
        "price": price,
        "currency": currency,
    }


def _region(region_id, name, status="ACTIVE"):
    return {
        "region_id": region_id,
        "name": name,
        "api_reference": region_id,
        "display_name": name,
        "aliases": [],
        "status": status,
    }


def _ours():
    return Ours(
        vendor="hcloud",
        servers=[
            _server("cx23", 2, 4096),
            _server("cx33", 4, 8000),  # memory stored as GB * 1000
            _server("cx99", 8, 16384),  # not listed by the vendor
            _server("ccx13", 2, 8192),  # outside the page's `covers`
            _server("cpx11", 2, 2048, status="INACTIVE"),
        ],
        server_prices=[
            _price("cx23", "fsn1", 0.0096),
            _price("cx33", "fsn1", 0.0200),
            _price("cx23", "ash", 0.0110),
        ],
        databases=[],
        database_prices=[],
        regions=[
            _region("fsn1", "Falkenstein"),
            _region("ash", "Ashburn", status="INACTIVE"),
        ],
        zones=[],
    )


def _vendor(complete=True):
    page = SourcePage(
        id="cost-optimized",
        url="https://www.hetzner.com/cloud/cost-optimized/",
        kinds=["server_specs", "server_prices"],
        covers="^cx\\d",
        complete=complete,
        currency="EUR",
    )
    return VendorSources(allowed_domains=["hetzner.com"], pages=[page])


def _write_extraction(out_dir, **rows):
    extraction = Extraction(
        vendor="hcloud",
        page_id="cost-optimized",
        extracted_at=datetime.now(UTC),
        extracted_by="test",
        **rows,
    )
    target = extracted_dir(out_dir, "hcloud")
    target.mkdir(parents=True)
    (target / f"{page_slug('cost-optimized')}.json").write_text(
        extraction.model_dump_json()
    )


SPECS = [
    {"sku": "CX23", "vcpus": 2, "memory_gib": 4, "evidence_quote": "CX23 2 vCPU 4 GB"},
    {"sku": "CX33", "vcpus": 4, "memory_gib": 8, "evidence_quote": "CX33 4 vCPU 8 GB"},
]


def _by(findings, type_, field=None):
    return [
        f for f in findings if f.type == type_ and (field is None or f.field == field)
    ]


def test_sku_keys_strip_vendor_prefixes():
    assert "d4sv5" in sku_keys("azure", "Standard_D4s_v5")
    assert "g7xlarge" in sku_keys("alicloud", "ecs.g7.xlarge")
    assert sku_keys("aws", "m5.large") == {"m5large"}


def test_memory_unit_mismatch(tmp_path):
    _write_extraction(tmp_path, servers=SPECS)
    findings, _ = compare_vendor("hcloud", _vendor(), _ours(), tmp_path)
    memory = _by(findings, "SPEC_MISMATCH", "memory_gib")
    assert [f.our_id for f in memory] == ["cx33"]
    assert memory[0].severity == "high"
    assert round(memory[0].diff_pct, 2) == -2.34


def test_not_at_vendor_only_for_complete_pages_and_covered_skus(tmp_path):
    _write_extraction(tmp_path, servers=SPECS)
    findings, _ = compare_vendor("hcloud", _vendor(complete=True), _ours(), tmp_path)
    assert [f.our_id for f in _by(findings, "NOT_AT_VENDOR")] == ["cx99"]

    other = tmp_path / "incomplete"
    _write_extraction(other, servers=SPECS)
    findings, _ = compare_vendor("hcloud", _vendor(complete=False), _ours(), other)
    assert not _by(findings, "NOT_AT_VENDOR")


def test_missing_in_db_and_status(tmp_path):
    specs = SPECS + [
        {"sku": "CX53", "vcpus": 16, "memory_gib": 32, "evidence_quote": "CX53"},
        {"sku": "CPX11", "vcpus": 2, "memory_gib": 2, "evidence_quote": "CPX11"},
    ]
    _write_extraction(tmp_path, servers=specs)
    findings, _ = compare_vendor("hcloud", _vendor(), _ours(), tmp_path)
    assert [f.sku for f in _by(findings, "MISSING_IN_DB")] == ["CX53"]
    assert [f.our_id for f in _by(findings, "STATUS_MISMATCH")] == ["cpx11"]


def test_prices_monthly_conversion_tolerance_and_inactive_regions(tmp_path):
    prices = [
        # 7.008 / 730 = 0.0096 -> matches
        {"sku": "CX23", "region": "fsn1", "price": 7.008, "unit": "month",
         "currency": "EUR", "evidence_quote": "€ 7.008 per month"},
        # 10% cheaper than ours
        {"sku": "CX33", "region": "fsn1", "price": 0.018, "unit": "hour",
         "currency": "EUR", "evidence_quote": "€ 0.018 per hour"},
        # region inactive in our data: skipped
        {"sku": "CX23", "region": "ash", "price": 1, "unit": "hour",
         "currency": "EUR", "evidence_quote": "ash"},
    ]  # fmt: skip
    _write_extraction(tmp_path, servers=SPECS, server_prices=prices)
    findings, stats = compare_vendor("hcloud", _vendor(), _ours(), tmp_path)
    mismatches = _by(findings, "PRICE_MISMATCH")
    assert [(f.our_id, f.severity) for f in mismatches] == [("cx33", "high")]
    assert stats["skipped_inactive_region"] == 1


def test_spec_signature_matching(tmp_path):
    specs = [
        {"sku": "Shared 2 vCPU", "vcpus": 2, "memory_gib": 4, "storage_gb": 40,
         "evidence_quote": "2 vCPU 4 GB 40 GB"},
    ]  # fmt: skip
    prices = [
        {"sku": "Shared 2 vCPU", "region": "fsn1", "price": 0.0096, "unit": "hour",
         "currency": "EUR", "evidence_quote": "€ 0.0096"},
    ]  # fmt: skip
    _write_extraction(tmp_path, servers=specs, server_prices=prices)
    findings, stats = compare_vendor(
        "hcloud", _vendor(complete=False), _ours(), tmp_path
    )
    assert not _by(findings, "MISSING_IN_DB")
    assert not _by(findings, "PRICE_MISMATCH")
    assert stats["server_prices"] == 1


def test_aws_parsers():
    assert _aws_storage("EBS only") == (0, None)
    assert _aws_storage("4 X 940 GB NVMe SSD") == (3760, "nvme ssd")
    assert _aws_storage("2 x 1900 NVMe SSD") == (3800, "nvme ssd")
    assert _aws_storage("8 x 3840 GB SSD") == (30720, "ssd")
    assert _aws_storage("1 x 2000 HDD") == (2000, "hdd")
    assert _aws_network("Up to 12.5 Gigabit") == 12.5
    assert _aws_network("100 Gigabit") == 100
    assert _aws_network("Low to Moderate") is None


def test_is_allowed():
    domains = ["hetzner.com"]
    assert is_allowed("https://www.hetzner.com/cloud/", domains)
    assert is_allowed("https://docs.hetzner.com/cloud/", domains)
    assert not is_allowed("http://www.hetzner.com/cloud/", domains)
    assert not is_allowed("https://hetzner.com.example.org/", domains)
    assert not is_allowed("https://nothetzner.com/", domains)


def test_retired_series_flags_active_family_members(tmp_path):
    ours = Ours(
        vendor="azure",
        servers=[
            _server("Standard_NC6s_v3", 6, 114688, family="NCSv3"),
            _server("Standard_D2s_v5", 2, 8192, family="Dsv5"),
        ],
        server_prices=[],
        databases=[],
        database_prices=[],
        regions=[],
        zones=[],
    )
    page = SourcePage(
        id="retired",
        url="https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/lifecycle/retired-sizes-list",
        kinds=["lifecycle"],
    )
    vendor = VendorSources(allowed_domains=["learn.microsoft.com"], pages=[page])
    extraction = Extraction(
        vendor="azure",
        page_id="retired",
        extracted_at=datetime.now(UTC),
        extracted_by="test",
        servers=[
            {"sku": "NCsv3-series", "status": "retired", "evidence_quote": "NCsv3"},
            {"sku": "Av1-series", "status": "retired", "evidence_quote": "Av1"},
        ],
    )
    target = extracted_dir(tmp_path, "azure")
    target.mkdir(parents=True)
    (target / "retired.json").write_text(extraction.model_dump_json())
    findings, _ = compare_vendor("azure", vendor, ours, tmp_path)
    assert [(f.type, f.our_id) for f in findings] == [
        ("STATUS_MISMATCH", "Standard_NC6s_v3")
    ]


def test_retired_plans_expect_retired_status(tmp_path):
    ours = _ours()
    ours.servers.append(_server("cx11", 1, 2048, status="INACTIVE"))
    ours.__post_init__()
    page = SourcePage(
        id="deprecated-plans",
        url="https://docs.hetzner.com/cloud/servers/deprecated-plans/",
        kinds=["lifecycle"],
    )
    vendor = VendorSources(allowed_domains=["hetzner.com"], pages=[page])
    extraction = Extraction(
        vendor="hcloud",
        page_id="deprecated-plans",
        extracted_at=datetime.now(UTC),
        extracted_by="test",
        servers=[
            {"sku": "CX11", "status": "retired", "evidence_quote": "CX11"},
            {"sku": "CX23", "status": "retiring", "evidence_quote": "CX23"},
        ],
    )
    target = extracted_dir(tmp_path, "hcloud")
    target.mkdir(parents=True)
    (target / "deprecated-plans.json").write_text(extraction.model_dump_json())
    findings, _ = compare_vendor("hcloud", vendor, ours, tmp_path)
    assert sorted((f.our_id, f.ours, f.severity) for f in findings) == [
        ("cx11", "INACTIVE", "low"),
        ("cx23", "ACTIVE", "medium"),
    ]


def test_source_conflict_when_another_page_agrees(tmp_path):
    vendor = VendorSources(
        allowed_domains=["hetzner.com"],
        pages=[
            SourcePage(
                id="docs", url="https://docs.hetzner.com/a", kinds=["server_specs"]
            ),
            SourcePage(
                id="feed", url="https://www.hetzner.com/b", kinds=["server_specs"]
            ),
        ],
    )
    target = extracted_dir(tmp_path, "hcloud")
    target.mkdir(parents=True)
    for page_id, vcpus in [("docs", 2), ("feed", 4)]:
        extraction = Extraction(
            vendor="hcloud",
            page_id=page_id,
            extracted_at=datetime.now(UTC),
            extracted_by="test",
            servers=[{"sku": "cx23", "vcpus": vcpus, "evidence_quote": "cx23"}],
        )
        (target / f"{page_id}.json").write_text(extraction.model_dump_json())
    findings, _ = compare_vendor("hcloud", vendor, _ours(), tmp_path)
    assert [(f.type, f.page_id, f.severity) for f in findings] == [
        ("SOURCE_CONFLICT", "feed", "low")
    ]


def test_secondary_source_mismatch_is_low_until_confirmed(tmp_path):
    feed = SourcePage(
        id="feed",
        url="https://www.hetzner.com/feed.json",
        kinds=["server_specs"],
        spec_authority=False,
    )
    docs = SourcePage(
        id="docs", url="https://docs.hetzner.com/a", kinds=["server_specs"]
    )
    target = extracted_dir(tmp_path, "hcloud")
    target.mkdir(parents=True)

    def write(page_id, vcpus):
        extraction = Extraction(
            vendor="hcloud",
            page_id=page_id,
            extracted_at=datetime.now(UTC),
            extracted_by="test",
            servers=[{"sku": "cx23", "vcpus": vcpus, "evidence_quote": "cx23"}],
        )
        (target / f"{page_id}.json").write_text(extraction.model_dump_json())

    # only the feed disagrees, no authoritative page: low, unconfirmed
    write("feed", 4)
    vendor = VendorSources(allowed_domains=["hetzner.com"], pages=[feed, docs])
    findings, _ = compare_vendor("hcloud", vendor, _ours(), tmp_path)
    assert [(f.type, f.severity) for f in findings] == [("SPEC_MISMATCH", "low")]
    assert "secondary source" in findings[0].note

    # the docs page confirms the vendor value: a real mismatch, found on both pages
    write("docs", 4)
    findings, _ = compare_vendor("hcloud", vendor, _ours(), tmp_path)
    assert [(f.type, f.severity) for f in findings] == [("SPEC_MISMATCH", "high")]
    assert {findings[0].page_id, *findings[0].also_on_pages} == {"docs", "feed"}


def test_iter_pages_ids_match_fetch_order(tmp_path):
    """A page linked from two parents gets the id of its first (breadth-first) parent."""
    import json

    from sc_crawler_audit.sources import discovered_path, iter_pages, pages_dir

    base = "https://learn.microsoft.com/sizes/"
    vendor = VendorSources(
        allowed_domains=["learn.microsoft.com"],
        pages=[
            SourcePage(
                id="sizes",
                url=base + "overview",
                kinds=["server_specs"],
                follow={
                    "pattern": "sizes/",
                    "kinds": ["server_specs"],
                    "recursive": True,
                },
            )
        ],
    )
    pages_dir(tmp_path, "azure").mkdir(parents=True)
    discovered_path(tmp_path, "azure").write_text(
        json.dumps(
            {
                "sizes": [base + "d-family", base + "dpdsv6-series"],
                "sizes/d-family": [base + "dpsv6-series", base + "dpdsv6-series"],
                "sizes/dpdsv6-series": [],
            }
        )
    )
    ids = {p.url: p.id for p in iter_pages(vendor.model_copy(), "azure", tmp_path)}
    assert ids[base + "dpdsv6-series"] == "sizes/dpdsv6-series"
    assert ids[base + "dpsv6-series"] == "sizes/d-family/dpsv6-series"


def test_triage_matching_pins_and_stale():
    from sc_crawler_audit.compare import Finding
    from sc_crawler_audit.triage import TriageEntry, apply_triage, load_triage

    def finding(our_id, ours, theirs):
        return Finding(
            vendor="gcp", type="SPEC_MISMATCH", severity="high", page_id="docs",
            url="https://cloud.google.com/x", independent=True, sku=our_id,
            our_id=our_id, field="memory_gib", ours=ours, theirs=theirs,
        )  # fmt: skip

    entries = [
        # pinned: applies only while both values are unchanged
        TriageEntry(
            vendor="gcp", type="SPEC_MISMATCH", field="memory_gib",
            match="db-f1-micro", ours="0.6", theirs="0.614",
            verdict="false_positive", note="GB vs GiB",
        ),
        TriageEntry(vendor="gcp", match="e2-.*", verdict="confirmed", note="bug"),
        TriageEntry(vendor="gcp", match="n9-.*", verdict="to_verify", note="gone"),
        TriageEntry(vendor="aws", match=".*", verdict="expected", note="other vendor"),
    ]  # fmt: skip
    findings = [
        finding("db-f1-micro", 0.6, 0.614),
        finding("db-g1-small", 1.7, 1.8),
        finding("e2-micro", 1.0, 2.0),
    ]
    findings, stale = apply_triage(findings, entries, vendors=["gcp"])
    assert [f.verdict for f in findings] == ["false_positive", None, "confirmed"]
    # only entries of compared vendors can be stale
    assert [e.match for e in stale] == ["n9-.*"]

    # changed value: the pinned verdict no longer applies, the finding is back
    findings, _ = apply_triage([finding("db-f1-micro", 0.5, 0.614)], entries, ["gcp"])
    assert findings[0].verdict is None

    # the bundled triage file is valid
    assert load_triage()


def test_archive_roundtrip(tmp_path):
    import tarfile

    from sc_crawler_audit.archive import create_archive, verify_archive

    run = tmp_path / "2026-01-01"
    (run / "pages" / "hcloud").mkdir(parents=True)
    (run / "pages" / "hcloud" / "cloud.md").write_text("# Hetzner\n")
    (run / "pages" / "hcloud" / "cloud.meta.json").write_text("{}")
    (run / "findings.jsonl").write_text("{}\n{}\n")

    path, manifest = create_archive(run)
    assert path == tmp_path / "2026-01-01.tar.xz"
    assert (tmp_path / "2026-01-01.manifest.json").exists()
    assert manifest["counts"] == {"pages": 1, "extractions": 0, "findings": 2}
    assert {f["path"] for f in manifest["files"]} == {
        "pages/hcloud/cloud.md",
        "pages/hcloud/cloud.meta.json",
        "findings.jsonl",
    }
    assert verify_archive(path) == []
    with tarfile.open(path) as tar:
        names = tar.getnames()
    assert "2026-01-01/manifest.json" in names
    assert "2026-01-01/config/sources.yaml" in names


def test_db_series_row_covers_family(tmp_path):
    def db(database_id, family):
        return {
            "database_id": database_id, "name": database_id, "api_reference": database_id,
            "display_name": database_id, "family": family, "series": None,
            "server_id": None, "status": "ACTIVE", "vcpus": 2, "memory_amount": 8192,
            "storage_size": None, "storage_extra_max": None, "engine_versions": [],
            "ha": [], "ha_strategy": [], "max_read_replicas": 5,
            "continuous_backups": 35, "scheduled_backups": 1, "sla": 99.99,
        }  # fmt: skip

    ours = Ours(
        vendor="azure",
        servers=[],
        server_prices=[],
        databases=[
            db("Standard_DC2ads_v5", "DCadsv5"),
            db("Standard_DC2as_v5", "DCasv5"),
        ],
        database_prices=[],
        regions=[],
        zones=[],
    )
    page = SourcePage(
        id="confidential",
        url="https://learn.microsoft.com/x",
        kinds=["db_specs"],
        covers="^Standard_(DC|EC)",
        complete=True,
    )
    vendor = VendorSources(allowed_domains=["learn.microsoft.com"], pages=[page])
    extraction = Extraction(
        vendor="azure",
        page_id="confidential",
        extracted_at=datetime.now(UTC),
        extracted_by="test",
        db_specs=[{"sku": "Dcadsv5", "evidence_quote": "| **Dcadsv5** | 2-96 |"}],
    )
    target = extracted_dir(tmp_path, "azure")
    target.mkdir(parents=True)
    (target / "confidential.json").write_text(extraction.model_dump_json())
    findings, _ = compare_vendor("azure", vendor, ours, tmp_path)
    assert [(f.type, f.our_id) for f in findings] == [
        ("NOT_AT_VENDOR", "Standard_DC2as_v5")
    ]
