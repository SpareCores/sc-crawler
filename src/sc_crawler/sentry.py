from asyncio import CancelledError
from contextlib import contextmanager
from os import environ

from .tables import Vendor

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
def sentry_capture_or_raise(vendor: Vendor, on_error=None):
    """Capture exception with Sentry and continue if configured, otherwise re-raise.

    Args:
        vendor (Vendor): Vendor to use for logging and progress bar updates.
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
            client = sentry_sdk.get_client()
            timeout = client.options.get("shutdown_timeout", 2)
            vendor.log(
                f"Sentry is attempting to send {captured_events} pending event(s), waiting up to {timeout}s."
            )
            sentry_sdk.flush(timeout=timeout)
        else:
            raise
