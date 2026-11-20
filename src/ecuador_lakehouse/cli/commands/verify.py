"""``lakehouse verify`` command: re-check a published artifact (S14)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ecuador_lakehouse.cli.guard import run_guarded
from ecuador_lakehouse.container import build_artifact_verifier


def verify(
    artifact_dir: Annotated[
        Path,
        typer.Argument(help="Published artifact directory to verify."),
    ],
) -> None:
    """Verify checksums, schemas, row counts and content fingerprints."""

    def command() -> None:
        result = build_artifact_verifier().execute(artifact_dir)
        typer.echo(
            f"verified {result.table_count} tables "
            f"(artifact {result.artifact_version}) at {result.artifact_dir}"
        )

    run_guarded(command)


def register(app: typer.Typer) -> None:
    """Attach the ``verify`` command to the root Typer application."""
    app.command("verify", help="Verify a published artifact (exit 8 on tampering).")(verify)
