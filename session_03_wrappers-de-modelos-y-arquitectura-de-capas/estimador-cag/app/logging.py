"""Structlog configuration and initialization."""

import logging
import structlog


def setup_logging(log_level: str) -> None:
    """Configure structlog with the given log level.

    Call once at application startup. Configures both structlog and the
    stdlib logging bridge so that third-party libraries (FastAPI, httpx, etc.)
    also emit structured output.

    Args:
        log_level: One of notset, debug, info, warning, warn, error, exception, critical.
    """
    level = getattr(logging, log_level.upper(), logging.DEBUG)

    logging.basicConfig(
        format="%(message)s",
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a structlog bound logger for the given module name.

    Args:
        name: Typically __name__ of the calling module.

    Returns:
        A structlog BoundLogger instance.
    """
    return structlog.get_logger(name)
