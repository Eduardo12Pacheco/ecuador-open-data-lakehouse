"""CLI error boundary and global option state (S24)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import typer
from typer.main import get_current_context  # type: ignore[attr-defined]

from ecuador_lakehouse.domain.errors import LakehouseError


@dataclass(frozen=True, slots=True)
class AppState:
    """Global CLI options resolved by the root callback."""

    debug: bool = False


def current_state() -> AppState:
    """Return the callback state, tolerating direct command invocation in tests."""
    try:
        context = get_current_context()
    except RuntimeError:
        return AppState()
    state = context.obj
    return state if isinstance(state, AppState) else AppState()


def run_guarded(command: Callable[[], None]) -> None:
    """Run a command, mapping expected errors to their documented exit code.

    ``LakehouseError`` carries the exit code (S24); unexpected exceptions map to
    exit code 1 and only show a traceback when ``--debug`` is enabled.
    """
    debug = current_state().debug
    try:
        command()
    except typer.Exit:
        raise
    except LakehouseError as error:
        typer.echo(f"Error: {error}", err=True)
        if debug:
            raise
        raise typer.Exit(code=error.exit_code) from None
    except Exception as error:
        typer.echo(f"Unexpected error: {error}", err=True)
        if debug:
            raise
        raise typer.Exit(code=1) from None
