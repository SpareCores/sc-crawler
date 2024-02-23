import logging

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
