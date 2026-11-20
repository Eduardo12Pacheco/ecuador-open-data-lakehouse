"""Tests for the full ``lakehouse doctor`` health check."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from ecuador_lakehouse.adapters.sources.reachability import HostProbe
from ecuador_lakehouse.cli.app import app
from ecuador_lakehouse.domain.errors import SourceUnavailableError

runner = CliRunner()


def test_doctor_reports_versions_home_and_sample(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAKEHOUSE_HOME", str(tmp_path))

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    for line in ("python: ", "duckdb: ", "dbt-core: ", "dbt-duckdb: "):
        assert line in result.output
    assert "home: OK (writable)" in result.output
    assert "sample: OK (12 files)" in result.output


def test_doctor_network_probes_all_hosts(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAKEHOUSE_HOME", str(tmp_path))
    probes = (
        HostProbe("descargas.sri.gob.ec", True, "HTTP 200"),
        HostProbe("www.ecuadorencifras.gob.ec", True, "HTTP 200"),
        HostProbe("www.datosabiertos.gob.ec", True, "HTTP 200"),
    )
    monkeypatch.setattr("ecuador_lakehouse.cli.commands.doctor.probe_hosts", lambda: probes)

    result = runner.invoke(app, ["doctor", "--network"])

    assert result.exit_code == 0
    assert "network: descargas.sri.gob.ec HTTP 200" in result.output
    assert "network: OK (3 hosts)" in result.output


def test_doctor_network_failure_exits_five(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAKEHOUSE_HOME", str(tmp_path))
    probes = (
        HostProbe("descargas.sri.gob.ec", False, "ConnectError"),
        HostProbe("www.ecuadorencifras.gob.ec", True, "HTTP 200"),
    )
    monkeypatch.setattr("ecuador_lakehouse.cli.commands.doctor.probe_hosts", lambda: probes)

    result = runner.invoke(app, ["doctor", "--network"])

    assert result.exit_code == 5
    assert "unreachable source hosts: descargas.sri.gob.ec" in result.output


def test_doctor_unwritable_home_maps_the_error(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LAKEHOUSE_HOME", str(tmp_path))

    def fail(_home: object) -> None:
        raise SourceUnavailableError("no write access")

    monkeypatch.setattr("ecuador_lakehouse.cli.commands.doctor._check_home", fail)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 5
    assert "no write access" in result.output
