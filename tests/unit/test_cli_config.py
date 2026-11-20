"""Tests that configuration problems exit cleanly with the documented code."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from ecuador_lakehouse.cli.app import app

runner = CliRunner()


def test_invalid_mode_exits_two_without_a_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAKEHOUSE_MODE", "bogus")

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 2
    assert "Configuration error" in result.output
    assert "mode" in result.output
    assert "bogus" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("LAKEHOUSE_MODE", "bogus"),
        ("LAKEHOUSE_SERVE_PORT", "70000"),
        ("LAKEHOUSE_YEARS", "2017,bogus"),
    ],
)
def test_every_invalid_setting_maps_to_exit_two(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 2
    assert "Configuration error" in result.output


def test_valid_environment_still_prints_the_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAKEHOUSE_MODE", "full")

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"
