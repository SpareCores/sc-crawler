"""Generate Markdown docs for the central Spare Cores docs site (Docusaurus).

Renders the API reference of the package with griffe2md, using the same griffe
extensions and object inventories as mkdocs.yml, and converts the hand-written
pages in docs/:

- cross-references to package objects become links between the generated pages,
- references to the standard library and other packages link out using their
  Sphinx inventories (objects.inv), others are rendered as plain code,
- mkdocs-only syntax is converted (autorefs, `<details markdown="1">`, the
  asciinema player, `!!!` labels).

The index page is MDX (it embeds the AsciinemaPlayer component of the docs
site), all other pages are plain Markdown, as docstrings might include
characters with special meaning in MDX.

Also writes the database schema as consumed by dbdocs (see
.github/workflows/dbdocs.yaml), for the Schemas section of the docs site.

Output, by default in build/docs-md:
- crawler/: the Crawler docs pages
- schema/: schema.sql (MySQL CREATE TABLE statements), project.dbml, and
  enums.json with the enum descriptions

Fails with the list of problems found, e.g. unresolved references to package
objects, docstring warnings or undocumented enum values, so that it can run as
a check on pull requests.

Usage: python scripts/gen_md_docs.py [OUTPUT_DIR]
"""

import json
import logging
import re
import shutil
import sys
import urllib.request
import zlib
from pathlib import Path

from griffe import Alias, GriffeLoader, Module, Object, Parser, load_extensions
from griffe2md import render_object_docs
from griffe2md._internal import rendering as griffe2md_rendering
from griffe2md._internal.config import default_config

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
DOCS = ROOT / "docs"
PACKAGE = "sc_crawler"
REPO_URL = "https://github.com/SpareCores/sc-crawler"
BRANCH = "main"

# same as the mkdocstrings handler options in mkdocs.yml
INVENTORIES = [
    "https://docs.python.org/3/objects.inv",
    "https://rich.readthedocs.io/en/stable/objects.inv",
    "https://docs.pydantic.dev/latest/objects.inv",
    "https://docs.sqlalchemy.org/en/20/objects.inv",
]
EXTENSIONS = [
    f"{ROOT}/scripts/dynamic_docstrings.py:DynamicDocstrings",
    "griffe_inherited_docstrings",
]
RENDER_CONFIG = {
    **default_config,
    # mkdocstrings defaults that differ from griffe2md's
    "show_if_no_docstring": False,
    "merge_init_into_class": False,
    "inherited_members": False,
    "show_submodules": False,
    # options from mkdocs.yml
    "show_signature": True,
    "separate_signature": True,
    "show_root_heading": True,
    "show_signature_annotations": False,
    "signature_crossrefs": True,
    "members_order": "source",
    "group_by_category": False,
    "summary": True,
    # one page per module: the module is the page title, its members are sections
    "heading_level": 1,
    # full paths in headings, shortened in `shorten_headings` after mapping anchors
    "show_root_full_path": True,
    "show_object_full_path": True,
}
# mkdocs syntax that should have been converted, as found in the output
LEFTOVER_SYNTAX = re.compile(r'\]\[[\w.]*\]|markdown="1"|^!!! |<script|^::: ', re.M)
# the pages that the docs site expects
REQUIRED_PAGES = ["index.mdx", "news.md", "add_vendor.md", "reference/index.md"]
MIN_REFERENCE_PAGES = 10

# everything that makes the output unfit for publishing, reported at the end
problems: list[str] = []


class ProblemHandler(logging.Handler):
    """Collects griffe's warnings, e.g. about malformed docstrings."""

    def emit(self, record: logging.LogRecord) -> None:
        problems.append(f"griffe: {record.getMessage()}")


# modules removed before the mkdocs build as well
SKIP_MODULES = re.compile(rf"^{PACKAGE}\.alembic(\.|$)|\.__main__$")


def _source_order(item: Object | Alias) -> int:
    """Sort by source line without resolving aliases.

    griffe2md orders members before filtering them, and resolving imported
    names from other packages (e.g. `logging`) fails.
    """
    lineno = item.alias_lineno if isinstance(item, Alias) else item.lineno
    return lineno if lineno is not None else -1


griffe2md_rendering.order_map["source"] = _source_order


def load_inventory(url: str) -> dict[str, str]:
    """Map object names to URLs from a Sphinx objects.inv file."""
    # readthedocs rejects the default urllib user agent
    request = urllib.request.Request(url, headers={"User-Agent": "sc-crawler-docs"})
    raw = urllib.request.urlopen(request, timeout=60).read()
    header_end = 0
    for _ in range(4):
        header_end = raw.index(b"\n", header_end) + 1
    base = url.rsplit("/", 1)[0] + "/"
    inventory = {}
    for line in zlib.decompress(raw[header_end:]).decode().splitlines():
        match = re.match(r"(.+?)\s+(\S+):(\S+)\s+(-?\d+)\s+(\S+)\s+(.*)", line)
        if not match or match.group(2) != "py":
            continue
        name, uri = match.group(1), match.group(5)
        if uri.endswith("$"):
            uri = uri[:-1] + name
        inventory.setdefault(name, base + uri)
    return inventory


def slugify(text: str, seen: dict[str, int]) -> str:
    """Heading anchor as generated by Docusaurus (github-slugger)."""
    slug = re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    return slug if count == 0 else f"{slug}-{count}"


def walk_modules(module: Module):
    if not SKIP_MODULES.search(module.path):
        yield module
    for member in module.modules.values():
        if not isinstance(member, Alias):
            yield from walk_modules(member)


def page_path(module: Module) -> str:
    """Output path of a module's page, without the package level.

    Docusaurus skips files starting with an underscore, so private modules
    (e.g. vendors._aws) lose the prefix in their file name, and treats a file
    named after its folder as the folder's index page, so e.g. vendors.vendors
    gets a suffix.
    """
    parts = [part.lstrip("_") for part in module.path.split(".")[1:]]
    if len(parts) > 1 and parts[-1] == parts[-2]:
        parts[-1] += "-module"
    if module.filepath.name == "__init__.py":
        parts.append("index")
    return "reference/" + "/".join(parts or ["index"]) + ".md"


def relative_link(from_page: str, to_page: str, anchor: str | None) -> str:
    suffix = f"#{anchor}" if anchor else ""
    if from_page == to_page:
        return suffix or "#"
    relative = (
        Path(to_page).relative_to(Path(from_page).parent, walk_up=True).as_posix()
    )
    return f"./{relative}{suffix}"


class Linker:
    """Resolves object paths to links within the generated pages or to external docs."""

    def __init__(
        self,
        loader: GriffeLoader,
        anchors: dict[str, tuple[str, str]],
        modules: set[str],
        inventory: dict[str, str],
    ):
        self.loader = loader
        self.anchors = anchors
        self.modules = modules
        self.inventory = inventory

    def link(self, page: str, path: str) -> str:
        to_page, anchor = self.anchors[path]
        # modules are page titles: link to the page itself
        return relative_link(page, to_page, None if path in self.modules else anchor)

    def canonical(self, path: str) -> str:
        """Follow aliases, e.g. sc_crawler.tables.Status -> sc_crawler.table_fields.Status."""
        for _ in range(10):
            try:
                obj = self.loader.modules_collection.get_member(path)
            except (KeyError, ValueError):
                return path
            if not isinstance(obj, Alias):
                return path
            path = obj.target_path
        return path

    def resolve(self, target: str, page: str) -> str | None:
        """URL for `target` as seen from `page`, None to render as plain text."""
        path = self.canonical(target)
        if path in self.anchors:
            return self.link(page, path)
        if path.startswith(PACKAGE + "."):
            # not an object of the package, e.g. a typo
            try:
                self.loader.modules_collection.get_member(path)
            except (KeyError, ValueError):
                return None
            # objects without their own section, e.g. attributes listed in the
            # class docstring: link to the closest documented parent, unless
            # that is on the same page anyway
            parent = path
            while "." in parent:
                parent = parent.rsplit(".", 1)[0]
                if parent in self.anchors:
                    return (
                        None
                        if self.anchors[parent][0] == page
                        else self.link(page, parent)
                    )
            return None
        return self.inventory.get(path) or self.inventory.get(target)


def code_links(html: str) -> str:
    """Turn griffe2md's <code> wrapped expressions into Markdown, keeping the links."""
    parts = re.split(r"(\[[^\]]*\]\([^)]*\))", html)
    out = []
    for part in parts:
        link = re.match(r"\[([^\]]*)\]\(([^)]*)\)", part)
        if link:
            out.append(f"[`{link.group(1)}`]({link.group(2)})")
        elif part:
            out.append(f"`{part}`")
    return "".join(out)


def render_reference(markdown: str, page: str, linker: Linker) -> str:
    def link(match: re.Match) -> str:
        text, target = match.group(1), match.group(2)
        url = linker.resolve(target, page)
        return f"[{text}]({url})" if url else text

    markdown = re.sub(r"\[([^\]]*)\]\(#([\w.]+)\)", link, markdown)
    # links inside <code> lost their target above: wrap the leftover text in backticks too
    return re.sub(
        r"<code>(.*?)</code>", lambda match: code_links(match.group(1)), markdown
    )


def convert_autorefs(markdown: str, page: str, linker: Linker) -> str:
    """mkdocs-autorefs `[text][path]` and `[path][]` references to links."""

    def link(match: re.Match) -> str:
        text, target = match.group(1), match.group(2) or match.group(1).strip("`")
        url = linker.resolve(target, page)
        if url is None:
            # other packages without an inventory are fine as plain text
            if target.startswith(PACKAGE + ".") or target == PACKAGE:
                problems.append(f"{page}: unresolved reference {target}")
            return text
        return f"[{text}]({url})"

    return re.sub(r"\[([^\]]+)\]\[([\w.]*)\]", link, markdown)


def front_matter(fields: dict) -> str:
    return (
        "---\n"
        + "".join(f"{key}: {json.dumps(value)}\n" for key, value in fields.items())
        + "---\n\n"
    )


def convert_index(markdown: str) -> tuple[str, list[str]]:
    """MDX version of docs/index.md, returning the asciinema recordings it uses."""
    # the title comes from front matter
    markdown = re.sub(r"\A## Spare Cores Crawler\n+", "", markdown)
    markdown = markdown.replace('<details markdown="1">', "<details>")
    # MDX has no autolinks and uses JS comments
    markdown = re.sub(r"<(https?://[^>]+)>", r"[\1](\1)", markdown)
    markdown = re.sub(r"<!--(.*?)-->", r"{/*\1*/}", markdown, flags=re.S)
    # asciinema: the <script> creates a player for each placeholder <div>
    script = re.search(r"<script>.*?</script>\n?", markdown, re.S)
    casts = dict(
        re.findall(
            r"AsciinemaPlayer\.create\(\s*'([^']+)',\s*document\.getElementById\('([^']+)'\)",
            script.group(0),
        )
    )
    casts = {element: cast for cast, element in casts.items()}
    markdown = markdown.replace(script.group(0), "")
    # the recordings are imported as assets, AsciinemaPlayer is provided by the docs site
    names = {cast: re.sub(r"\W", "_", cast) for cast in casts.values()}
    markdown = re.sub(
        r'<div id="([^"]+)"[^>]*></div>',
        lambda match: f"<AsciinemaPlayer src={{{names[casts[match.group(1)]]}}} />",
        markdown,
    )
    imports = "".join(
        f"import {name} from './{cast}';\n" for cast, name in names.items()
    )
    return f"{imports}\n{markdown}", list(casts.values())


def docstring(obj: Object | Alias | None) -> str:
    return obj.docstring.value.strip() if obj is not None and obj.docstring else ""


def enum_docs(loader: GriffeLoader) -> dict:
    """Descriptions of the enums used in the tables, which the SQL can't hold.

    The values are documented in attribute docstrings, available only in the
    source code (via griffe), while the columns using them are known by SQLAlchemy.
    """
    from sqlalchemy import Enum as SqlEnum

    from sc_crawler.tables import tables

    enums: dict[str, dict] = {}
    columns: dict[str, dict[str, str]] = {}
    for table in tables:
        for column in table.__table__.columns:
            enum_class = (
                getattr(column.type, "enum_class", None)
                if isinstance(column.type, SqlEnum)
                else None
            )
            if enum_class is None:
                continue
            columns.setdefault(table.__tablename__, {})[column.name] = (
                enum_class.__name__
            )
            if enum_class.__name__ in enums:
                continue
            documented = loader.modules_collection.get_member(
                f"{enum_class.__module__}.{enum_class.__qualname__}"
            )
            enums[enum_class.__name__] = {
                "description": docstring(documented),
                # the database stores the member names
                "values": [
                    {
                        "name": name,
                        "description": docstring(documented.members.get(name)),
                    }
                    for name in enum_class.__members__
                ],
            }
    return {"enums": dict(sorted(enums.items())), "columns": columns}


def write_schema(output: Path, loader: GriffeLoader) -> None:
    """Same CREATE TABLE statements and project note as published to dbdocs,
    plus the enum descriptions."""
    from typer.testing import CliRunner

    from sc_crawler.cli import cli

    result = CliRunner().invoke(cli, ["schemas", "create", "--dialect", "mysql"])
    if result.exit_code != 0:
        raise RuntimeError(f"sc-crawler schemas create failed: {result.output}")
    output.mkdir(parents=True)
    (output / "schema.sql").write_text(result.stdout)
    shutil.copy(ROOT / "project.dbml", output / "project.dbml")
    enums = enum_docs(loader)
    (output / "enums.json").write_text(json.dumps(enums, indent=2) + "\n")

    from sc_crawler.tables import tables

    for table in tables:
        if (
            f"CREATE TABLE `{table.__tablename__}`" not in result.stdout
            and f"CREATE TABLE {table.__tablename__} " not in result.stdout
        ):
            problems.append(f"schema: missing CREATE TABLE for {table.__tablename__}")
    for name, enum in enums["enums"].items():
        if not enum["description"]:
            problems.append(f"schema: enum {name} has no docstring")
        for value in enum["values"]:
            if not value["description"]:
                problems.append(
                    f"schema: enum value {name}.{value['name']} has no docstring"
                )
    print(f"  schema: {len(enums['enums'])} enums")
    print(f"  schema: {result.stdout.count('CREATE TABLE')} tables")


def main(output: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    docs = output / "crawler"
    docs.mkdir(parents=True)

    print("Loading inventories")
    inventory: dict[str, str] = {}
    for url in INVENTORIES:
        for name, link in load_inventory(url).items():
            inventory.setdefault(name, link)

    print(f"Loading {PACKAGE}")
    logging.getLogger("griffe").addHandler(ProblemHandler(logging.WARNING))
    loader = GriffeLoader(
        extensions=load_extensions(*EXTENSIONS),
        search_paths=[str(SRC), *sys.path],
        docstring_parser=Parser.google,
    )
    package = loader.load(PACKAGE)
    loader.resolve_aliases(external=False)
    write_schema(output / "schema", loader)

    # render all pages first to know which heading each object got
    pages: dict[str, tuple[Module, str]] = {}
    anchors: dict[str, tuple[str, str]] = {}
    for module in walk_modules(package):
        page = page_path(module)
        markdown = render_object_docs(module, RENDER_CONFIG)
        seen: dict[str, int] = {}

        def shorten_headings(match: re.Match) -> str:
            level, path = match.group(1), match.group(2)
            # module path as page title, members relative to the module
            text = path if path == module.path else path.removeprefix(module.path + ".")
            anchors[path] = (page, slugify(text, seen))
            return f"{level} `{text}`"

        markdown = re.sub(r"^(#+) `([\w.]+)`$", shorten_headings, markdown, flags=re.M)
        pages[page] = (module, markdown)

    linker = Linker(
        loader, anchors, {module.path for module, _ in pages.values()}, inventory
    )
    for page, (module, markdown) in pages.items():
        source = module.relative_package_filepath.as_posix()
        target = docs / page
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            front_matter(
                {
                    "sidebar_label": module.name,
                    # plain text: autorefs are kept as their text only
                    "description": (
                        re.sub(
                            r"\[([^\]]+)\]\[[\w.]*\]",
                            r"\1",
                            module.docstring.value.splitlines()[0],
                        )
                        if module.docstring
                        else module.path
                    ),
                    "custom_edit_url": f"{REPO_URL}/blob/{BRANCH}/src/{source}",
                    "mdx": {"format": "md"},
                }
            )
            # docstrings might use autorefs as well
            + convert_autorefs(render_reference(markdown, page, linker), page, linker)
        )
    (docs / "reference" / "_category_.json").write_text(
        json.dumps({"label": "Reference", "position": 4}, indent=2)
    )
    print(f"  {len(pages)} reference pages")

    # hand-written pages
    index, casts = convert_index((DOCS / "index.md").read_text())
    (docs / "index.mdx").write_text(
        front_matter(
            {
                "title": "Spare Cores Crawler",
                "sidebar_label": "Overview",
                "sidebar_position": 1,
                "custom_edit_url": f"{REPO_URL}/edit/{BRANCH}/docs/index.md",
            }
        )
        + convert_autorefs(index, "index.mdx", linker)
    )
    for cast in casts:
        shutil.copy(DOCS / cast, docs / cast)

    add_vendor = (DOCS / "add_vendor.md").read_text()
    (docs / "add_vendor.md").write_text(
        front_matter(
            {
                "sidebar_position": 3,
                "custom_edit_url": f"{REPO_URL}/edit/{BRANCH}/docs/add_vendor.md",
                "mdx": {"format": "md"},
            }
        )
        + convert_autorefs(add_vendor, "add_vendor.md", linker)
    )

    changelog = (ROOT / "CHANGELOG.md").read_text()
    # not a valid mkdocs admonition either (no indented content): keep it as a label
    changelog = re.sub(r"^!!! (.+)$", r"**\1**", changelog, flags=re.M)
    # named and placed like the News page of the API docs
    (docs / "news.md").write_text(
        front_matter(
            {
                "title": "News",
                "sidebar_position": 2,
                "custom_edit_url": f"{REPO_URL}/edit/{BRANCH}/CHANGELOG.md",
                "mdx": {"format": "md"},
            }
        )
        + convert_autorefs(changelog, "news.md", linker)
    )
    print(f"Written to {output}")
    check_output(output)


def check_output(output: Path) -> None:
    """Sanity checks on the written files, on top of the problems collected while writing."""
    docs = output / "crawler"
    for page in REQUIRED_PAGES:
        if not (docs / page).is_file() or not (docs / page).read_text().strip():
            problems.append(f"missing or empty page: crawler/{page}")
    if len(list((docs / "reference").rglob("*.md"))) < MIN_REFERENCE_PAGES:
        problems.append(f"fewer than {MIN_REFERENCE_PAGES} reference pages")
    for file in sorted(docs.rglob("*.md*")):
        for match in LEFTOVER_SYNTAX.finditer(file.read_text()):
            problems.append(
                f"{file.relative_to(docs)}: unconverted mkdocs syntax {match.group(0)!r}"
            )


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "docs-md")
    if problems:
        print(f"\n{len(problems)} problem(s) found:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        sys.exit(1)
