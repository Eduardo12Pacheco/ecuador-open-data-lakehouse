"""``lakehouse test`` command: run the quality gate only (S11, S13)."""

from __future__ import annotations

import typer

from ecuador_lakehouse.cli.guard import run_guarded
from ecuador_lakehouse.cli.presenters import quality_line
from ecuador_lakehouse.config import get_settings
from ecuador_lakehouse.container import build_container


def test() -> None:
    """Run the dbt data and unit tests and exit 7 when any test fails."""

    def command() -> None:
        container = build_container(get_settings())
        try:
            report = container.pipeline.run(only="quality")
        finally:
            container.close()
        typer.echo(quality_line(report))

    run_guarded(command)


def register(app: typer.Typer) -> None:
    """Attach the ``test`` command to the root Typer application."""
    app.command("test", help="Run the dbt data and unit tests (quality gate).")(test)
