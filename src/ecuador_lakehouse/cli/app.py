"""Command-line interface for the Ecuador open-data lakehouse."""

from __future__ import annotations

import contextlib

import typer
from typer.main import get_current_context  # type: ignore[attr-defined]

from ecuador_lakehouse import __version__
from ecuador_lakehouse.cli.commands import (
    build,
    contract,
    docs,
    doctor,
    fetch,
    publish,
    sample,
    test,
    verify,
)
from ecuador_lakehouse.cli.guard import AppState
from ecuador_lakehouse.config import Settings, get_settings
from ecuador_lakehouse.domain.errors import LakehouseError

app = typer.Typer(
    name="lakehouse",
    help="Local-first analytics-engineering lakehouse over Ecuadorian open data.",
    no_args_is_help=True,
    add_completion=False,
)
fetch.register(app)
sample.register(app)
doctor.register(app)
docs.register(app)
build.register(app)
test.register(app)
publish.register(app)
verify.register(app)
contract.register(app)


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
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Show the full traceback for unexpected errors.",
    ),
) -> None:
    """Ecuador open-data lakehouse command line."""
    _load_settings()
    with contextlib.suppress(RuntimeError):
        get_current_context().obj = AppState(debug=debug)


def main() -> None:
    """Console-script entry point."""
    app()
