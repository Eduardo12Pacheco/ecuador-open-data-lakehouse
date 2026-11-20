"""``lakehouse doctor`` command: integrity check of the bundled sample (S3)."""

from __future__ import annotations

import typer

from ecuador_lakehouse.config import get_settings
from ecuador_lakehouse.container import verify_sample_integrity
from ecuador_lakehouse.domain.errors import LakehouseError


def doctor() -> None:
    """Check the bundled sample against its manifest."""
    try:
        settings = get_settings()
        count = verify_sample_integrity(settings)
    except LakehouseError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=error.exit_code) from None
    typer.echo(f"sample: OK ({count} files)")


def register(app: typer.Typer) -> None:
    """Attach the ``doctor`` command to the root Typer application."""
    app.command("doctor", help="Check the local installation and bundled sample.")(doctor)
