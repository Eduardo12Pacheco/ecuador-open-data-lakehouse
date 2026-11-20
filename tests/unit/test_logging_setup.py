"""Tests for structlog configuration in console and JSON formats."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest
import structlog

from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.logging_setup import configure_logging


@pytest.fixture(autouse=True)
def _reset_logging() -> Iterator[None]:
    yield
    structlog.reset_defaults()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)


def test_json_format_emits_one_structured_line() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", log_format="json", stream=stream)

    structlog.get_logger("test").info("partition loaded", partition="2024", rows=42)

    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert payload["event"] == "partition loaded"
    assert payload["level"] == "info"
    assert payload["partition"] == "2024"
    assert payload["rows"] == 42
    assert "timestamp" in payload


def test_console_format_is_human_readable() -> None:
    stream = io.StringIO()
    configure_logging(level="DEBUG", log_format="console", stream=stream)

    structlog.get_logger("test").debug("hello", partition="2024")

    output = stream.getvalue()
    assert "hello" in output
    assert "2024" in output


@pytest.mark.parametrize("level", ["TRACE", "verbose", ""])
def test_invalid_level_is_a_config_error(level: str) -> None:
    with pytest.raises(ConfigError, match="log level"):
        configure_logging(level=level, log_format="console", stream=io.StringIO())


@pytest.mark.parametrize("log_format", ["xml", "", "CONSOLE"])
def test_invalid_format_is_a_config_error(log_format: str) -> None:
    with pytest.raises(ConfigError, match="log format"):
        configure_logging(level="INFO", log_format=log_format, stream=io.StringIO())


def test_level_is_case_insensitive() -> None:
    stream = io.StringIO()
    configure_logging(level="warning", log_format="json", stream=stream)

    structlog.get_logger("test").warning("careful")

    assert json.loads(stream.getvalue().strip())["level"] == "warning"
