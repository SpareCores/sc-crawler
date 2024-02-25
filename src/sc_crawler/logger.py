from __future__ import annotations
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from rich.progress import (
    track,
    Progress,
    TextColumn,
    BarColumn,
    MofNCompleteColumn,
    TimeRemainingColumn,
    TimeElapsedColumn,
    SpinnerColumn,
)
from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.rule import Rule
from rich.padding import Padding
from rich.align import Align
from rich.logging import RichHandler
from rich.traceback import Traceback

logger = logging.getLogger("sc_crawler")
logger.addHandler(logging.NullHandler())


def log_start_end(func):
    """Log the start and end of the decorated function."""

    def wrap(*args, **kwargs):
        try:
            self = args[0]
            fname = f"{self.id}/{func.__name__}"
        except Exception:
            fname = func.__name__
        logger.debug("Starting %s", fname)
        result = func(*args, **kwargs)
        logger.debug("Finished %s", fname)
        return result

    return wrap


# https://github.com/Textualize/rich/issues/1532#issuecomment-1062431265
class ScRichHandler(RichHandler):
    """Extend RichHandler with function name logged in the right column."""

    def render(
        self,
        *,
        record: logging.LogRecord,
        traceback: Optional[Traceback],
        message_renderable: "ConsoleRenderable",
    ):
        path = Path(record.pathname).name + ":" + record.funcName
        level = self.get_level_text(record)
        time_format = None if self.formatter is None else self.formatter.datefmt
        log_time = datetime.fromtimestamp(record.created)

        log_renderable = self._log_render(
            self.console,
            [message_renderable] if not traceback else [message_renderable, traceback],
            log_time=log_time,
            time_format=time_format,
            level=level,
            path=path,
            line_no=record.lineno,
            link_path=record.pathname if self.enable_link_path else None,
        )
        return log_renderable


class ProgressPanel:
    vendors: Progress = Progress(
        TimeElapsedColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("({task.completed} of {task.total} steps)"),
        TimeRemainingColumn(),
    )
    tasks: Progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=True,
    )
    metadata: Text = Text(justify="left")
    panels: Table = Table.grid(padding=1)

    def __init__(self, *args, **kwargs):
        self.panels.add_row(
            Group(
                Panel(
                    self.metadata,
                    title="SC Crawler v" + version("sc_crawler"),
                    title_align="left",
                ),
                Panel(
                    self.vendors,
                    title="Vendors",
                    title_align="left",
                ),
            ),
            Panel(
                self.tasks,
                title="Running tasks",
                title_align="left",
                expand=False,
            ),
        )

    def add_task(self, description: str, n: int):
        self.tasks.add_task(description, total=n)

    def add_vendor(self, vendor_name: str, steps: int):
        self.vendors.add_task(vendor_name, total=steps)

if TYPE_CHECKING:
    from .schemas import Vendor


class VendorProgressTracker:
    """Tracing the progress of the vendor's inventory."""

    vendor: Vendor
    progress_panel: ProgressPanel
    vendor_progress: Optional[Progress] = None

    def __init__(self, vendor: Vendor, progress_panel: ProgressPanel):
        self.vendor = vendor
        self.progress_panel = progress_panel

    def vendor_steps_init(self, n: int) -> Progress:
        """Starts a progress bar for the Vendor's steps."""
        self.vendor_progress = self.progress_panel.vendors.add_task(
            self.vendor.name, total=n
        )
        return self.vendor_progress

    def vendor_steps_advance(self, by: int = 1):
        """Increment the number of finished steps."""
        self.progress_panel.vendors.update(self.vendor_progress, advance=by)
