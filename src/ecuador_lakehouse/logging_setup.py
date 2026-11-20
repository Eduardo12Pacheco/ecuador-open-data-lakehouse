"""Structlog configuration for console and JSON output (D21, S24)."""

from __future__ import annotations

import logging
import sys
from typing import Any, TextIO

import structlog

from ecuador_lakehouse.domain.errors import ConfigError

_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
_FORMATS = frozenset({"console", "json"})


def configure_logging(
    level: str = "INFO",
    log_format: str = "console",
    *,
    stream: TextIO | None = None,
) -> None:
    """Configure stdlib logging and structlog with the requested level and format.

    ``stream`` exists for tests and embedding; production writes to stderr.
    """
    level_name = level.strip().upper()
    if level_name not in _LEVELS:
        raise ConfigError(f"invalid log level: {level!r} (choose from {', '.join(_LEVELS)})")
    if log_format not in _FORMATS:
        raise ConfigError(f"invalid log format: {log_format!r} (choose console or json)")

    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(_LEVELS[level_name])

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        timestamper,
    ]
    renderer: Any
    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
        )
    )
