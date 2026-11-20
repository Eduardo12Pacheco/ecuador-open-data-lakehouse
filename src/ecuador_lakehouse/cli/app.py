"""Command-line interface for the Ecuador open-data lakehouse."""

from __future__ import annotations

import typer

from ecuador_lakehouse import __version__
from ecuador_lakehouse.cli.commands import fetch
from ecuador_lakehouse.config import Settings, get_settings
from ecuador_lakehouse.domain.errors import LakehouseError

app = typer.Typer(
    name="lakehouse",
    help="Local-first analytics-engineering lakehouse over Ecuadorian open data.",
    no_args_is_help=True,
    add_completion=False,
)
fetch.register(app)


def _load_settings() -> Settings:
    """Load settings, turning invalid configuration into a clean exit code 2."""
    try:
        return get_settings()
    except LakehouseError as error:
        typer.echo(f"Configuration error: {error}", err=True)
        raise typer.Exit(code=error.exit_code) from None


def _print_version(value: bool) -> None:
    """Print the installed package version and exit when ``--version`` is given."""
    if value:
        _load_settings()
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_print_version,
        is_eager=True,
        help="Print the installed package version and exit.",
    ),
) -> None:
    """Ecuador open-data lakehouse command line."""
    _load_settings()


def main() -> None:
    """Console-script entry point."""
    app()
