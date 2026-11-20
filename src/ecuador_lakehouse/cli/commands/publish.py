"""``lakehouse publish`` command: write the versioned data product (S14)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ecuador_lakehouse.cli.guard import run_guarded
from ecuador_lakehouse.config import get_settings
from ecuador_lakehouse.container import build_container
from ecuador_lakehouse.domain.errors import ConfigError


def publish(
    out: Annotated[
        Path,
        typer.Option("--out", help="Directory where the artifact directory is written."),
    ] = Path("dist-artifact"),
) -> None:
    """Publish the built marts as a verified, versioned artifact."""

    def command() -> None:
        settings = get_settings()
        warehouse = settings.home / "warehouse.duckdb"
        if not warehouse.is_file():
            raise ConfigError("no warehouse yet - run: lakehouse build")
        container = build_container(settings, publish_out=out)
        try:
            container.warehouse.close()
            result = container.publish_artifact.execute()
        finally:
            container.close()
        typer.echo(f"published {result.table_count} tables to {result.artifact_dir}")

    run_guarded(command)


def register(app: typer.Typer) -> None:
    """Attach the ``publish`` command to the root Typer application."""
    app.command("publish", help="Publish the marts as a versioned artifact.")(publish)
