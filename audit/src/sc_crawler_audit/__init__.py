"""Cross-check the published sc-data against official vendor sources.

See the project README (`audit/README.md`) for the workflow and design.
"""

from pathlib import Path

__version__ = "0.1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
"""The `audit/` project directory, holding `sources.yaml` and `triage.yaml`."""
