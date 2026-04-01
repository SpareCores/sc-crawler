from asyncio import CancelledError
from contextlib import contextmanager
from os import environ

captured_events = 0


def before_send(event, hint):
    """Do not report intended shutdown errors to sentry."""
    global captured_events
    exc_info = hint.get("exc_info")
    if exc_info:
        exc_type, exc_value, tb = exc_info
        ignore_exc_types = (
            CancelledError,
            KeyboardInterrupt,
            SystemExit,
        )
        if issubclass(exc_type, ignore_exc_types):
            return None
    captured_events += 1
    return event


@contextmanager
def sentry_capture_or_raise(on_error=None):
    """Capture exception with Sentry and continue if configured, otherwise re-raise.

    Args:
        on_error: Optional callable that receives the exception and is always
            called before capturing or re-raising (e.g. for logging or state updates).
    """
    try:
        yield
    except Exception as e:
        if on_error:
            on_error(e)
        if environ.get("SENTRY_DSN"):
            import sentry_sdk

            sentry_sdk.capture_exception(e)
        else:
            raise
