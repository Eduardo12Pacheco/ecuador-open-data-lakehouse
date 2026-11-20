"""Unit tests for the ``lakehouse serve`` command wiring (S16)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ecuador_lakehouse.application.use_cases.build_report import ReportResult
from ecuador_lakehouse.cli.app import app
from ecuador_lakehouse.cli.commands import serve as serve_module

runner = CliRunner()


class FakeServer:
    """Stand-in for the loopback HTTP server used by the command."""

    def __init__(self) -> None:
        self.started = False
        self.closed = False

    def serve_forever(self) -> None:
        self.started = True

    def server_close(self) -> None:
        self.closed = True


class FakeReport:
    """Stand-in build-report use case."""

    def __init__(self) -> None:
        self.calls = 0

    def execute(self) -> ReportResult:
        self.calls += 1
        return ReportResult(path=Path("index.html"), batch_count=12)


class FakeContainer:
    """Minimal container exposing only the report use case."""

    def __init__(self, report: FakeReport) -> None:
        self.build_report = report
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_serve_without_warehouse_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["serve", "--no-open"],
        env={"LAKEHOUSE_HOME": str(tmp_path), "LAKEHOUSE_SERVE_PORT": "15081"},
    )
    assert result.exit_code == 2
    assert "No data yet - run: lakehouse build" in result.output


def test_serve_rejects_non_loopback_host(tmp_path: Path) -> None:
    (tmp_path / "warehouse.duckdb").write_text("", encoding="utf-8")
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<!doctype html>", encoding="utf-8")
    result = runner.invoke(
        app,
        ["serve", "--no-open", "--host", "0.0.0.0"],  # noqa: S104 - rejected host
        env={"LAKEHOUSE_HOME": str(tmp_path)},
    )
    assert result.exit_code == 2
    assert "loopback" in result.output


def test_serve_builds_the_site_when_missing_and_starts_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "warehouse.duckdb").write_text("", encoding="utf-8")
    report = FakeReport()
    container = FakeContainer(report)
    server = FakeServer()
    opened: list[str] = []

    monkeypatch.setattr(serve_module, "build_container", lambda settings: container)
    monkeypatch.setattr(serve_module, "create_server", lambda site, host, port: server)
    monkeypatch.setattr(serve_module, "server_url", lambda bound: "http://127.0.0.1:15081")
    monkeypatch.setattr(serve_module.webbrowser, "open", opened.append)

    result = runner.invoke(
        app,
        ["serve", "--no-open", "--port", "15081"],
        env={"LAKEHOUSE_HOME": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    assert report.calls == 1
    assert container.closed
    assert server.started
    assert server.closed
    assert opened == []
    assert "http://127.0.0.1:15081" in result.output


def test_serve_opens_the_browser_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "warehouse.duckdb").write_text("", encoding="utf-8")
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<!doctype html>", encoding="utf-8")
    server = FakeServer()
    opened: list[str] = []

    monkeypatch.setattr(serve_module, "create_server", lambda site, host, port: server)
    monkeypatch.setattr(serve_module, "server_url", lambda bound: "http://127.0.0.1:15081")
    monkeypatch.setattr(serve_module.webbrowser, "open", opened.append)

    result = runner.invoke(
        app,
        ["serve", "--port", "15081"],
        env={"LAKEHOUSE_HOME": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    assert opened == ["http://127.0.0.1:15081"]


def test_invalid_port_is_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "warehouse.duckdb").write_text("", encoding="utf-8")
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<!doctype html>", encoding="utf-8")
    result = runner.invoke(
        app,
        ["serve", "--no-open", "--port", "70000"],
        env={"LAKEHOUSE_HOME": str(tmp_path)},
    )
    assert result.exit_code == 2
    assert "invalid port" in result.output
