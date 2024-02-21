import logging

logger = logging.getLogger("sc_crawler")
logger.addHandler(logging.NullHandler())


def log_start_end(func):
    """Log the start and end of the decorated function."""

    def wrap(*args, **kwargs):
        logger.debug(f"Starting {func.__name__}")
        result = func(*args, **kwargs)
        logger.debug(f"Finished {func.__name__}")
        return result

    return wrap
