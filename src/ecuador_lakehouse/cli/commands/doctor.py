"""``lakehouse doctor`` command: local installation health check (S1, S3)."""

from __future__ import annotations

import platform
import tempfile
from importlib import metadata
from pathlib import Path

import typer

from ecuador_lakehouse.adapters.sources.reachability import probe_hosts
from ecuador_lakehouse.cli.guard import run_guarded
from ecuador_lakehouse.config import get_settings
from ecuador_lakehouse.container import verify_sample_integrity
from ecuador_lakehouse.domain.errors import ConfigError, SourceUnavailableError


def _distribution_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "unknown"


def _check_home(home: Path) -> None:
    try:
        home.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".lakehouse-doctor-", dir=home, delete=False
        ) as handle:
            handle.write(b"ok")
            probe = Path(handle.name)
    except OSError as error:
        raise ConfigError(f"LAKEHOUSE_HOME is not writable: {error}") from error
    finally:
        probe.unlink(missing_ok=True)


def _run(network: bool) -> None:
    settings = get_settings()
    _check_home(settings.home)
    typer.echo(f"python: {platform.python_version()}")
    typer.echo(f"duckdb: {_distribution_version('duckdb')}")
    typer.echo(f"dbt-core: {_distribution_version('dbt-core')}")
    typer.echo(f"dbt-duckdb: {_distribution_version('dbt-duckdb')}")
    typer.echo("home: OK (writable)")
    count = verify_sample_integrity(settings)
    typer.echo(f"sample: OK ({count} files)")
    if network:
        probes = probe_hosts()
        unreachable = [probe for probe in probes if not probe.ok]
        for probe in probes:
            typer.echo(f"network: {probe.host} {probe.detail}")
        if unreachable:
            names = ", ".join(probe.host for probe in unreachable)
            raise SourceUnavailableError(f"unreachable source hosts: {names}")
        typer.echo(f"network: OK ({len(probes)} hosts)")


def doctor(
    network: bool = typer.Option(
        False,
        "--network",
        help="Also probe the three upstream source hosts (network access required).",
    ),
) -> None:
    """Check versions, home writability, the bundled sample and (optionally) sources."""

    def command() -> None:
        _run(network)

    run_guarded(command)


def register(app: typer.Typer) -> None:
    """Attach the ``doctor`` command to the root Typer application."""
    app.command("doctor", help="Check the local installation and bundled sample.")(doctor)
