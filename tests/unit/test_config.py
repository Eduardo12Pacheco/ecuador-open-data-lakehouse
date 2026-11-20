"""Tests for the typed, environment-driven settings (decision D20)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ecuador_lakehouse.config import Settings, get_settings
from ecuador_lakehouse.domain.errors import ConfigError


def test_defaults_match_the_documented_configuration() -> None:
    settings = Settings()

    assert settings.mode == "sample"
    assert settings.log_level == "INFO"
    assert settings.log_format == "console"
    assert settings.http_timeout_s == 30.0
    assert settings.http_retries == 3
    assert settings.serve_host == "127.0.0.1"
    assert 15_000 <= settings.serve_port <= 15_999
    assert settings.dbt_threads == 4
    assert settings.years == tuple(range(2017, 2027))
    assert isinstance(settings.home, Path)
    assert settings.home.is_absolute()


def test_environment_overrides_every_documented_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LAKEHOUSE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("LAKEHOUSE_MODE", "full")
    monkeypatch.setenv("LAKEHOUSE_LOG_LEVEL", "debug")
    monkeypatch.setenv("LAKEHOUSE_LOG_FORMAT", "json")
    monkeypatch.setenv("LAKEHOUSE_HTTP_TIMEOUT_S", "12.5")
    monkeypatch.setenv("LAKEHOUSE_HTTP_RETRIES", "0")
    monkeypatch.setenv("LAKEHOUSE_SERVE_HOST", "localhost")
    monkeypatch.setenv("LAKEHOUSE_SERVE_PORT", "15099")
    monkeypatch.setenv("LAKEHOUSE_DBT_THREADS", "2")
    monkeypatch.setenv("LAKEHOUSE_YEARS", "2019,2021-2022")

    settings = Settings()

    assert settings.home == tmp_path / "home"
    assert settings.mode == "full"
    assert settings.log_level == "DEBUG"
    assert settings.log_format == "json"
    assert settings.http_timeout_s == 12.5
    assert settings.http_retries == 0
    assert settings.serve_host == "localhost"
    assert settings.serve_port == 15099
    assert settings.dbt_threads == 2
    assert settings.years == (2019, 2021, 2022)


def test_years_accepts_a_single_year_and_a_reversed_duplicate_free_range() -> None:
    assert Settings(years="2024").years == (2024,)
    assert Settings(years=(2026, 2017, 2017)).years == (2017, 2026)
    assert Settings(years=2024).years == (2024,)
    assert Settings(years=range(2020, 2022)).years == (2020, 2021)


@pytest.mark.parametrize(
    "years", ["", "2017,bogus", "2025-2020", "1999", "2101", "2017-", "-2020", "2017--2020"]
)
def test_years_rejects_invalid_selections(years: str) -> None:
    with pytest.raises(ValueError, match="year"):
        Settings(years=years)


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": "bogus"},
        {"log_level": "TRACE"},
        {"log_format": "xml"},
        {"http_timeout_s": 0},
        {"http_retries": -1},
        {"serve_port": 80},
        {"serve_port": 70_000},
        {"dbt_threads": 0},
        {"serve_host": ""},
    ],
)
def test_settings_rejects_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(**overrides)  # type: ignore[arg-type]


def test_get_settings_wraps_validation_errors_as_config_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LAKEHOUSE_MODE", "bogus")

    with pytest.raises(ConfigError, match="mode"):
        get_settings()


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAKEHOUSE_SERVE_PORT", "15090")

    first = get_settings()
    monkeypatch.setenv("LAKEHOUSE_SERVE_PORT", "15091")
    second = get_settings()

    assert first is second
    assert second.serve_port == 15090

    get_settings.cache_clear()

    assert get_settings().serve_port == 15091
