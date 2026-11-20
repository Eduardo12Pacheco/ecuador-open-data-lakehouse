"""``lakehouse docs`` command: static dbt docs plus optional Mermaid lineage (S12)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ecuador_lakehouse.config import get_settings
from ecuador_lakehouse.container import build_container
from ecuador_lakehouse.domain.errors import LakehouseError


def docs(
    mermaid: Annotated[
        Path | None,
        typer.Option(
            "--mermaid",
            help="Also write the model DAG as Mermaid Markdown to this path.",
        ),
    ] = None,
) -> None:
    """Generate the offline dbt documentation site and optional lineage file."""
    container = None
    try:
        settings = get_settings()
        container = build_container(settings)
        result = container.build_docs.execute(mermaid_path=mermaid)
    except LakehouseError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=error.exit_code) from None
    finally:
        if container is not None:
            container.close()

    typer.echo(f"dbt docs: {result.site_index}")
    if result.mermaid_path is not None:
        typer.echo(f"lineage: {result.mermaid_path}")


def register(app: typer.Typer) -> None:
    """Attach the ``docs`` command to the root Typer application."""
    app.command("docs", help="Generate dbt static docs and Mermaid lineage.")(docs)
