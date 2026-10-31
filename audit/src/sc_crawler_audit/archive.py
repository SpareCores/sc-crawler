"""Pack an audit run into a single archive for long-term storage (e.g. S3 or Google Drive).

Raw vendor pages are too large and noisy for git (and copies of third-party
content should not be published), but they are the evidence behind every
finding. The archive keeps the whole run directory together with a manifest:
checksums of all files, the audited data dump, the git commit of the tool, and
copies of the `sources.yaml` and `triage.yaml` that were used.
"""

import hashlib
import io
import json
import sqlite3
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from . import PROJECT_ROOT, __version__

MANIFEST = "manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(*args: str) -> Optional[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _db_metadata(db: Optional[Path]) -> dict:
    if not db or not Path(db).expanduser().exists():
        return {}
    try:
        uri = f"file:{Path(db).expanduser()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            return dict(conn.execute("SELECT key, value FROM _metadata").fetchall())
    except sqlite3.Error:
        return {}


def build_manifest(run_dir: Path, db: Optional[Path] = None) -> dict:
    run_dir = Path(run_dir)
    files = sorted(p for p in run_dir.rglob("*") if p.is_file())
    status = _git("status", "--porcelain", "--", ".")
    return {
        "run": run_dir.name,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tool": {
            "name": "sc-crawler-audit",
            "version": __version__,
            "git_commit": _git("rev-parse", "HEAD"),
            "git_dirty": bool(status) if status is not None else None,
        },
        "data": {
            "db": str(db) if db else None,
            **{
                k: v
                for k, v in _db_metadata(db).items()
                if k in ("published_at", "published_by", "sc_crawler_version")
            },
        },
        "counts": {
            "pages": sum(1 for p in files if p.parts[-3:-2] == ("pages",)
                         and p.name.endswith(".meta.json")),
            "extractions": sum(1 for p in files if "extracted" in p.parts),
            "findings": _count_lines(run_dir / "findings.jsonl"),
        },
        "files": [
            {
                "path": str(p.relative_to(run_dir)),
                "bytes": p.stat().st_size,
                "sha256": _sha256(p),
            }
            for p in files
        ],
    }  # fmt: skip


def _count_lines(path: Path) -> Optional[int]:
    if not path.exists():
        return None
    with open(path) as fh:
        return sum(1 for _ in fh)


def create_archive(
    run_dir: Path, output: Optional[Path] = None, db: Optional[Path] = None
) -> tuple[Path, dict]:
    """Write `<run>.tar.xz` (and `<run>.manifest.json` next to it)."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")
    output = Path(output or run_dir.parent / f"{run_dir.name}.tar.xz")
    manifest = build_manifest(run_dir, db)
    manifest_bytes = json.dumps(manifest, indent=2).encode()

    with tarfile.open(output, "w:xz") as tar:
        tar.add(run_dir, arcname=run_dir.name)
        for config in ("sources.yaml", "triage.yaml"):
            if (PROJECT_ROOT / config).exists():
                tar.add(
                    PROJECT_ROOT / config, arcname=f"{run_dir.name}/config/{config}"
                )
        info = tarfile.TarInfo(f"{run_dir.name}/{MANIFEST}")
        info.size = len(manifest_bytes)
        info.mtime = int(datetime.now(UTC).timestamp())
        tar.addfile(info, io.BytesIO(manifest_bytes))

    sidecar = output.with_name(f"{run_dir.name}.manifest.json")
    manifest["archive"] = {
        "file": output.name,
        "bytes": output.stat().st_size,
        "sha256": _sha256(output),
    }
    sidecar.write_text(json.dumps(manifest, indent=2))
    return output, manifest


def verify_archive(archive: Path) -> list[str]:
    """Check the files in an archive against its manifest; returns the problems."""
    problems = []
    with tarfile.open(archive, "r:xz") as tar:
        members = {m.name: m for m in tar.getmembers() if m.isfile()}
        manifest_name = next((n for n in members if n.endswith(f"/{MANIFEST}")), None)
        if manifest_name is None:
            return ["manifest.json is missing"]
        root = manifest_name.rsplit("/", 1)[0]
        manifest = json.load(tar.extractfile(members[manifest_name]))
        for entry in manifest["files"]:
            member = members.get(f"{root}/{entry['path']}")
            if member is None:
                problems.append(f"missing: {entry['path']}")
                continue
            digest = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
            if digest != entry["sha256"]:
                problems.append(f"checksum mismatch: {entry['path']}")
    return problems
