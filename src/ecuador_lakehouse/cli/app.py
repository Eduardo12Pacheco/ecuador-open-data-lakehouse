"""Command-line interface for the Ecuador open-data lakehouse."""

from __future__ import annotations

import typer

from ecuador_lakehouse import __version__

app = typer.Typer(
    name="lakehouse",
    help="Local-first analytics-engineering lakehouse over Ecuadorian open data.",
    no_args_is_help=True,
    add_completion=False,
)


def _print_version(value: bool) -> None:
    """Print the installed package version and exit when ``--version`` is given."""
    if value:
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


def main() -> None:
    """Console-script entry point."""
    app()
