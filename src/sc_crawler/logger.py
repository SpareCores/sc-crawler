from __future__ import annotations

import logging
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from rich.console import ConsoleRenderable, Group
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text
from rich.traceback import Traceback

logger = logging.getLogger("sc_crawler")
logger.addHandler(logging.NullHandler())


def log_start_end(func):
    """Log the start and end of the decorated function."""

    def wrap(*args, **kwargs):
        # log start of the step
        try:
            self = args[0]
            fname = f"{self.vendor_id}/{func.__name__}"
        except Exception:
            fname = func.__name__
        logger.debug("Starting %s", fname)

        # update Vendor's progress bar with the step name
        try:
            self.progress_tracker.update_vendor(
                # drop `inventory_` prefix and prettify
                step=func.__name__[10:].replace("_", " ")
            )
        except Exception:
            logger.error("Cannot update step name in the Vendor's progress bar.")

        # actually run step
        result = func(*args, **kwargs)

        # increment Vendor's progress bar
        self.progress_tracker.advance_vendor()

        # log end of the step and return
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
        TextColumn("({task.completed} of {task.total} steps): {task.fields[step]}"),
        expand=False,
    )
    tasks: Progress = Progress(
        TimeElapsedColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        expand=False,
        transient=True,
    )
    metadata: Text = Text(justify="left")
    panels: Table = Table.grid(padding=1)

    def __init__(self, *args, **kwargs):
        self.panels.add_row(
            Group(
                Panel(
                    self.metadata,
                    title="SC Crawler v" + version("sparecores-crawler"),
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
        return self.tasks.add_task(description, total=n)

    def add_vendor(self, vendor_name: str, steps: int):
        return self.vendors.add_task(vendor_name, total=steps)


if TYPE_CHECKING:
    from .tables import Vendor


class VendorProgressTracker:
    """Tracking the progress of the vendor's inventory updates."""

    vendor: Vendor
    """A [sc_crawler.tables.Vendor][] instance for which tracking progress."""
    progress_panel: ProgressPanel
    """
    A `rich` panel including progress bars.
    Should not be used directly, see the `vendors`, `tasks` and `metadata` attributes.
    """
    # reexport Progress attributes of the ProgressPanel
    vendors: Progress
    """[rich.progress.Progress][] for tracking the inventory steps of the vendor."""
    tasks: Progress
    """[rich.progress.Progress][] for tracking the lower-level tasks within each step."""
    metadata: Text
    """[rich.text.Text][] metadata, e.g. data sources and records to be udpated."""
    task_ids: List[TaskID] = []
    """List of active task ids for the current `vendor`."""

    def __init__(self, vendor: Vendor, progress_panel: ProgressPanel):
        self.vendor = vendor
        self.progress_panel = progress_panel
        self.vendors = progress_panel.vendors
        self.tasks = progress_panel.tasks
        self.metadata = progress_panel.metadata

    def start_vendor(self, total: int) -> TaskID:
        """Starts a progress bar for the Vendor's steps.

        Args:
            total: Overall number of steps to show in the progress bar.

        Returns:
            TaskId: The progress bar's identifier to be referenced in future updates.
        """
        return self.vendors.add_task(self.vendor.name, total=total, step="")

    def advance_vendor(self, advance: int = 1) -> None:
        """Increment the number of finished steps.

        Args:
            advance: Number of steps to advance.
        """
        self.vendors.update(self.vendors.task_ids[-1], advance=advance)

    def update_vendor(self, **kwargs) -> None:
        """Update the vendor's progress bar.

        Useful fields:
        - `step`: Name of the currently running step to be shown on the progress bar.
        """
        self.vendors.update(self.vendors.task_ids[-1], **kwargs)

    def start_task(self, name: str, total: int) -> TaskID:
        """Starts a progress bar in the list of current jobs.

        Besides returning the `TaskID`, it will also register in `self.tasks.task_ids`
        as the last task, which will be the default value for future `advance_task`,
        `hide_task` etc calls. The latter will remove the `TaskID` from the `task_ids`.

        Args:
            name: Name to show in front of the progress bar. Will be prefixed by Vendor's name.
            total: Overall number of steps to show in the progress bar.

        Returns:
            TaskId: The progress bar's identifier to be referenced in future updates.
        """
        self.task_ids.append(
            self.tasks.add_task(self.vendor.name + ": " + name, total=total)
        )
        return self.last_task()

    def last_task(self) -> TaskID:
        """Returh the last registered TaskID."""
        return self.task_ids[-1]

    def advance_task(self, task_id: Optional[TaskID] = None, advance: int = 1):
        """Increment the number of finished steps.

        Args:
            task_id: The progress bar's identifier returned by `start_task`.
                Defaults to the most recently created task.
            advance: Number of steps to advance.
        """

        self.tasks.update(task_id or self.last_task(), advance=advance)

    def update_task(self, task_id: Optional[TaskID] = None, **kwargs) -> None:
        """Update the task's progress bar.

        Args:
            task_id: The progress bar's identifier returned by `start_task`.
                Defaults to the most recently created task.

        Keyword Args:
            step (str): Name of the currently running step to be shown on the progress bar.

        See [`rich.progress.Progress.update`][] for further keyword arguments.
        """
        self.tasks.update(task_id or self.last_task(), **kwargs)

    def hide_task(self, task_id: Optional[TaskID] = None):
        """Hide a task from the list of progress bars.

        Args:
            task_id: The progress bar's identifier returned by `start_task`.
                Defaults to the most recently created task.
        """
        self.tasks.update(task_id or self.last_task(), visible=False)
        self.task_ids.pop()
