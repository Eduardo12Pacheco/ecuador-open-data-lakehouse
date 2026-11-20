"""Typed application settings loaded from ``LAKEHOUSE_*`` environment variables.

Decision D20 fixes the variable names and defaults; the CLI overrides the few
settings it exposes as flags after construction.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Annotated, Literal

import platformdirs
from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from ecuador_lakehouse.domain.errors import ConfigError

_MIN_YEAR = 2000
_MAX_YEAR = 2100
_MIN_PORT = 1024
_MAX_PORT = 65535
_MAX_ERROR_INPUT_LENGTH = 120


def default_home() -> Path:
    """Return the per-user data directory for warehouses, dbt runs and sites."""
    return Path(platformdirs.user_data_dir("ecuador-lakehouse", appauthor=False))


class Settings(BaseSettings):
    """All runtime configuration, validated at construction time."""

    model_config = SettingsConfigDict(
        env_prefix="LAKEHOUSE_",
        case_sensitive=False,
        extra="ignore",
    )

    home: Path = Field(default_factory=default_home)
    mode: Literal["sample", "full"] = "sample"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["console", "json"] = "console"
    http_timeout_s: float = Field(default=30.0, gt=0, le=600)
    http_retries: int = Field(default=3, ge=0, le=10)
    serve_host: str = Field(default="127.0.0.1", min_length=1)
    serve_port: int = Field(default=15080, ge=_MIN_PORT, le=_MAX_PORT)
    dbt_threads: int = Field(default=4, ge=1, le=32)
    years: Annotated[tuple[int, ...], NoDecode] = tuple(range(2017, 2027))

    @field_validator("home", mode="before")
    @classmethod
    def _absolute_home(cls, value: object) -> Path:
        path = Path(str(value)).expanduser()
        return path if path.is_absolute() else Path.cwd() / path

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("years", mode="before")
    @classmethod
    def _parse_years(cls, value: object) -> tuple[int, ...]:
        if isinstance(value, str):
            years = _parse_year_selection(value)
        elif isinstance(value, int) and not isinstance(value, bool):
            years = (value,)
        elif isinstance(value, (list, tuple, set, range)):
            years = tuple(int(item) for item in value)
        else:
            return value  # type: ignore[return-value]
        unique = tuple(sorted(set(years)))
        if not unique:
            raise ValueError("years must not be empty")
        if any(year < _MIN_YEAR or year > _MAX_YEAR for year in unique):
            raise ValueError(f"years must be between {_MIN_YEAR} and {_MAX_YEAR}")
        return unique


def parse_years(raw: str) -> tuple[int, ...]:
    """Parse ``2024`` / ``2019,2021-2022`` into a sorted, de-duplicated tuple."""
    years = _parse_year_selection(raw)
    unique = tuple(sorted(set(years)))
    if not unique:
        raise ValueError("years must not be empty")
    if any(year < _MIN_YEAR or year > _MAX_YEAR for year in unique):
        raise ValueError(f"years must be between {_MIN_YEAR} and {_MAX_YEAR}")
    return unique


def _parse_year_selection(raw: str) -> tuple[int, ...]:
    text = raw.strip()
    if not text:
        raise ValueError("years must not be empty")
    years: list[int] = []
    for raw_token in text.split(","):
        token = raw_token.strip()
        if not token:
            raise ValueError(f"invalid year selection: {raw!r}")
        if "-" in token:
            start_text, _, end_text = token.partition("-")
            if not start_text or not end_text or "-" in end_text:
                raise ValueError(f"invalid year range: {token!r}")
            try:
                start, end = int(start_text), int(end_text)
            except ValueError as exc:
                raise ValueError(f"invalid year range: {token!r}") from exc
            if start > end:
                raise ValueError(f"year range is reversed: {token!r}")
            years.extend(range(start, end + 1))
        else:
            try:
                years.append(int(token))
            except ValueError as exc:
                raise ValueError(f"invalid year: {token!r}") from exc
    return tuple(years)


def _format_validation_error(error: ValidationError) -> str:
    parts: list[str] = []
    for detail in error.errors(include_url=False):
        location = ".".join(str(part) for part in detail["loc"]) or "<root>"
        message = f"{location}: {detail['msg']}"
        invalid = detail.get("input")
        is_scalar = isinstance(invalid, str | int | float | bool)
        if is_scalar and len(str(invalid)) <= _MAX_ERROR_INPUT_LENGTH:
            message += f" (got {invalid!r})"
        parts.append(message)
    return "; ".join(parts)


@cache
def get_settings() -> Settings:
    """Return the cached process settings, raising :class:`ConfigError` when invalid."""
    try:
        return Settings()
    except ValidationError as error:
        raise ConfigError(f"invalid configuration: {_format_validation_error(error)}") from error
