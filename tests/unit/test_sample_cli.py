"""Tests for the ``lakehouse sample`` and ``lakehouse doctor`` commands."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from ecuador_lakehouse.cli.app import app
from ecuador_lakehouse.domain.errors import ChecksumMismatchError

runner = CliRunner()


def test_root_help_lists_the_sample_and_doctor_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "sample" in result.output
    assert "doctor" in result.output


def test_sample_build_help_lists_the_maintainer_options() -> None:
    result = runner.invoke(app, ["sample", "build", "--help"])

    assert result.exit_code == 0
    for option in ("--years", "--cache-dir", "--output-dir", "--seed-dir"):
        assert option in result.output


def test_sample_build_rejects_invalid_years_with_exit_two() -> None:
    result = runner.invoke(app, ["sample", "build", "--years", "2019-bogus"])

    assert result.exit_code == 2
    assert "invalid --years" in result.output
    assert "Traceback" not in result.output


def test_doctor_reports_a_checksum_failure_with_exit_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_settings: object) -> int:
        raise ChecksumMismatchError("checksum mismatch for bundled sample")

    monkeypatch.setattr("ecuador_lakehouse.cli.commands.doctor.verify_sample_integrity", fail)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 3
    assert "checksum mismatch" in result.output
    assert "Traceback" not in result.output
