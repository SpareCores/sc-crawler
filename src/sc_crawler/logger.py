import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

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
