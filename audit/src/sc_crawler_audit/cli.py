"""The `sc-audit` CLI."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, List, Optional

import typer
from rich.console import Console
from rich.table import Table

from .sources import load_sources, selected_vendors

app = typer.Typer(
    help="Cross-check the published sc-data against official vendor pages. "
    "See audit/README.md and the vendor-audit Claude Code skill for the workflow.",
    no_args_is_help=True,
)
console = Console()

options = SimpleNamespace(
    vendor=Annotated[
        Optional[List[str]],
        typer.Option(help="Vendor id(s) to audit. Can be repeated. Defaults to all."),
    ],
    exclude_vendor=Annotated[
        Optional[List[str]],
        typer.Option(help="Vendor id(s) to skip. Can be repeated."),
    ],
    out=Annotated[
        Path,
        typer.Option(help="Directory of the audit run (pages, extractions, findings)."),
    ],
    sources=Annotated[
        Optional[Path],
        typer.Option(help="Path to a sources YAML file instead of the bundled one."),
    ],
    db=Annotated[
        Path,
        typer.Option(help="Path to the SQLite dump of sc-data to audit."),
    ],
)
default_out = Path("audit-out") / date.today().isoformat()
default_db = Path("~/downloads/sc-data-all.db").expanduser()


@app.command()
def fetch(
    vendor: options.vendor = None,
    exclude_vendor: options.exclude_vendor = None,
    out: options.out = default_out,
    sources: options.sources = None,
    page: Annotated[
        Optional[str], typer.Option(help="Regex to fetch only matching page ids.")
    ] = None,
    cache_ttl: Annotated[
        int, typer.Option(help="Reuse pages fetched within this many hours.")
    ] = 24,
    dry_run: Annotated[
        bool, typer.Option(help="Only check the URLs, without saving anything.")
    ] = False,
):
    """Download the official vendor pages and convert them to Markdown."""
    from .fetch import fetch_vendor

    table = Table("vendor", "page", "status", "KiB", "md chars", "rows", "flags")
    problems = 0

    def progress(r):
        nonlocal problems
        flags = []
        if r.error:
            flags.append(f"[red]{r.error}[/red]")
        if r.js_suspect and not r.error:
            flags.append("[yellow]JS-rendered?[/yellow]")
        elif r.no_tables and not r.error:
            flags.append("no tables")
        if r.cached:
            flags.append("cached")
        if r.error or r.js_suspect:
            problems += 1
        table.add_row(
            r.vendor,
            r.page_id,
            str(r.status),
            str(r.raw_bytes // 1024),
            str(r.markdown_chars),
            str(r.table_rows),
            " ".join(flags),
        )
        console.log(f"{r.vendor}/{r.page_id}: {r.status} {' '.join(flags)}")

    for vendor_id, vendor_sources in selected_vendors(
        load_sources(sources), vendor, exclude_vendor
    ):
        fetch_vendor(
            vendor_id,
            vendor_sources,
            out,
            ttl=timedelta(hours=cache_ttl),
            dry_run=dry_run,
            page_filter=page,
            progress=progress,
        )
    console.print(table)
    console.print(f"{problems} page(s) with errors or likely JS-rendered content.")


@app.command()
def parse(
    vendor: options.vendor = None,
    exclude_vendor: options.exclude_vendor = None,
    out: options.out = default_out,
    sources: options.sources = None,
):
    """Run the deterministic parsers on fetched machine-readable pages."""
    from .parsers import PARSERS
    from .sources import extracted_dir, iter_pages, page_slug, pages_dir

    for vendor_id, vendor_sources in selected_vendors(
        load_sources(sources), vendor, exclude_vendor
    ):
        for page in iter_pages(vendor_sources, vendor_id, out):
            if not page.parser:
                continue
            raw = pages_dir(out, vendor_id) / f"{page_slug(page.id)}.json"
            if not raw.exists():
                console.log(f"[yellow]{vendor_id}/{page.id}: not fetched[/yellow]")
                continue
            extraction = PARSERS[page.parser](raw.read_bytes(), page, vendor_id)
            target = extracted_dir(out, vendor_id)
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{page_slug(page.id)}.json").write_text(
                extraction.model_dump_json(indent=2, exclude_defaults=True)
            )
            console.log(
                f"{vendor_id}/{page.id}: {len(extraction.servers)} servers, "
                f"{len(extraction.server_prices)} server prices, "
                f"{len(extraction.db_specs)} db specs, "
                f"{len(extraction.db_prices)} db prices"
            )


@app.command()
def pending(
    vendor: options.vendor = None,
    exclude_vendor: options.exclude_vendor = None,
    out: options.out = default_out,
    sources: options.sources = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
):
    """List fetched pages that still need LLM extraction."""
    from .sources import extracted_dir, iter_pages, page_slug, pages_dir

    rows = []
    for vendor_id, vendor_sources in selected_vendors(
        load_sources(sources), vendor, exclude_vendor
    ):
        for page in iter_pages(vendor_sources, vendor_id, out):
            slug = page_slug(page.id)
            md = pages_dir(out, vendor_id) / f"{slug}.md"
            done = (extracted_dir(out, vendor_id) / f"{slug}.json").exists()
            if page.parser or not md.exists() or done:
                continue
            rows.append(
                {
                    "vendor": vendor_id,
                    "page_id": page.id,
                    "markdown": str(md),
                    "output": str(extracted_dir(out, vendor_id) / f"{slug}.json"),
                    "kinds": [k.value for k in page.kinds],
                    "region": page.region,
                    "currency": page.currency,
                    "notes": page.notes,
                    "chars": md.stat().st_size,
                }
            )
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    table = Table("vendor", "page", "kinds", "chars")
    for row in rows:
        table.add_row(
            row["vendor"], row["page_id"], ",".join(row["kinds"]), str(row["chars"])
        )
    console.print(table)


@app.command()
def schema():
    """Print the JSON schema of the extraction files."""
    from .schema import Extraction

    print(json.dumps(Extraction.model_json_schema(), indent=2))


@app.command()
def validate(
    vendor: options.vendor = None,
    exclude_vendor: options.exclude_vendor = None,
    out: options.out = default_out,
    sources: options.sources = None,
):
    """Validate the extraction files against the schema."""
    from pydantic import ValidationError

    from .schema import Extraction
    from .sources import extracted_dir

    failed = 0
    for vendor_id, _ in selected_vendors(load_sources(sources), vendor, exclude_vendor):
        for path in sorted(extracted_dir(out, vendor_id).glob("*.json")):
            try:
                extraction = Extraction.model_validate_json(path.read_text())
                if extraction.vendor != vendor_id:
                    raise ValueError(f"vendor is {extraction.vendor}, not {vendor_id}")
            except (ValidationError, ValueError) as e:
                failed += 1
                console.print(f"[red]{path}[/red]\n{e}")
    console.print(f"{failed} invalid extraction file(s).")
    if failed:
        raise typer.Exit(code=1)


@app.command()
def export(
    vendor: options.vendor = None,
    exclude_vendor: options.exclude_vendor = None,
    out: options.out = default_out,
    sources: options.sources = None,
    db: options.db = default_db,
):
    """Dump our records used by the comparison (reference regions only for prices)."""
    from .export import load_ours

    for vendor_id, vendor_sources in selected_vendors(
        load_sources(sources), vendor, exclude_vendor
    ):
        ours = load_ours(db, vendor_id)
        target = Path(out) / "ours"
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{vendor_id}.json").write_text(
            json.dumps(
                ours.to_dict(vendor_sources.reference_regions), indent=2, default=str
            )
        )
        console.log(f"{vendor_id}: {ours.summary()}")


@app.command()
def compare(
    vendor: options.vendor = None,
    exclude_vendor: options.exclude_vendor = None,
    out: options.out = default_out,
    sources: options.sources = None,
    db: options.db = default_db,
    price_tolerance: Annotated[
        float, typer.Option(help="Relative tolerance for price comparisons.")
    ] = 0.01,
    triage: Annotated[
        Optional[Path],
        typer.Option(help="Triage YAML to apply instead of the bundled triage.yaml."),
    ] = None,
):
    """Compare the extracted vendor data with our records and write a report."""
    from .compare import compare_vendor
    from .export import load_ours
    from .report import write_report
    from .triage import apply_triage, load_triage

    findings, stats = [], {}
    loaded = load_sources(sources)
    for vendor_id, vendor_sources in selected_vendors(loaded, vendor, exclude_vendor):
        ours = load_ours(db, vendor_id)
        vendor_findings, vendor_stats = compare_vendor(
            vendor_id, vendor_sources, ours, out, price_tolerance=price_tolerance
        )
        findings.extend(vendor_findings)
        stats[vendor_id] = vendor_stats
        console.log(f"{vendor_id}: {len(vendor_findings)} findings, {vendor_stats}")
    entries = load_triage(triage)
    findings, stale = apply_triage(findings, entries, list(stats))
    triaged = sum(f.verdict is not None for f in findings)
    console.log(
        f"Triage: {len(entries)} entries, {triaged} findings matched, "
        f"{len(stale)} stale entries"
    )
    path = write_report(findings, stats, out, db, datetime.now(UTC), stale)
    console.print(f"Report written to {path}")


@app.command("seed-urls")
def seed_urls(
    root: Annotated[
        Path, typer.Option(help="Root of the sc-crawler repository checkout.")
    ] = Path("."),
    sources: options.sources = None,
    output: Annotated[
        Path, typer.Option(help="Where to write the candidate sources.")
    ] = Path("audit-out/sources.candidates.yaml"),
):
    """Collect vendor URLs referenced in our code and docs as candidate sources."""
    import yaml

    from .seed import collect_urls

    candidates = collect_urls(root, load_sources(sources))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(candidates, sort_keys=False, width=120))
    for vendor_id, urls in candidates.items():
        new = sum(not u["in_sources"] for u in urls)
        console.log(f"{vendor_id}: {len(urls)} URLs, {new} not yet in sources")
    console.print(f"Candidates written to {output}")


@app.command()
def archive(
    out: options.out = default_out,
    db: options.db = default_db,
    output: Annotated[
        Optional[Path],
        typer.Option(help="Archive path. Defaults to <out>.tar.xz next to the run."),
    ] = None,
    verify: Annotated[
        bool, typer.Option(help="Re-read the archive and check all checksums.")
    ] = True,
):
    """Pack a run (pages, extractions, findings, config) for long-term storage."""
    from .archive import create_archive, verify_archive

    path, manifest = create_archive(out, output, db)
    console.print(
        f"Archive: {path} ({manifest['archive']['bytes'] / 1e6:.1f} MB, "
        f"{len(manifest['files'])} files, sha256 {manifest['archive']['sha256'][:12]}...)"
    )
    console.print(f"Manifest: {path.with_name(Path(out).name + '.manifest.json')}")
    if verify:
        problems = verify_archive(path)
        for problem in problems:
            console.print(f"[red]{problem}[/red]")
        if problems:
            raise typer.Exit(code=1)
        console.print("Verified: all checksums match.")


@app.command("verify-archive")
def verify_archive_cmd(
    path: Annotated[
        Path, typer.Argument(help="Archive created by `sc-audit archive`.")
    ],
):
    """Check all files of a (downloaded) archive against its manifest."""
    from .archive import verify_archive

    problems = verify_archive(path)
    for problem in problems:
        console.print(f"[red]{problem}[/red]")
    if problems:
        raise typer.Exit(code=1)
    console.print(f"{path}: all checksums match.")


@app.command("import-page")
def import_page_cmd(
    vendor: Annotated[str, typer.Argument(help="Vendor id, e.g. vultr.")],
    page: Annotated[str, typer.Argument(help="Page id from sources.yaml.")],
    file: Annotated[Path, typer.Argument(help="HTML file saved from a browser.")],
    out: options.out = default_out,
    sources: options.sources = None,
):
    """Import a page saved manually from a browser (for pages blocking automated clients)."""
    from .fetch import import_page

    vendor_sources = load_sources(sources).vendors[vendor]
    matches = [p for p in vendor_sources.pages if p.id == page]
    if not matches:
        console.print(f"[red]No page {page!r} for {vendor} in sources.yaml[/red]")
        raise typer.Exit(code=1)
    result = import_page(vendor, matches[0], file, out)
    console.print(
        f"{vendor}/{page}: imported {result.raw_bytes // 1024} KiB, "
        f"{result.markdown_chars} Markdown chars, {result.table_rows} table rows"
        + (
            " [yellow](little content: save the fully loaded page)[/yellow]"
            if result.js_suspect or result.no_tables
            else ""
        )
    )
