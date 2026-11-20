"""``lakehouse build`` command: run the full pipeline DAG (S13)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ecuador_lakehouse.cli.guard import run_guarded
from ecuador_lakehouse.cli.presenters import print_run
from ecuador_lakehouse.config import get_settings
from ecuador_lakehouse.container import build_container


def build(
    select: Annotated[
        list[str] | None,
        typer.Option(
            "--select",
            help="Run these steps plus all of their upstream steps (repeatable).",
        ),
    ] = None,
    only: Annotated[
        str | None,
        typer.Option("--only", help="Run exactly one step, with no upstream steps."),
    ] = None,
    from_step: Annotated[
        str | None,
        typer.Option("--from-step", help="Run this step and every step after it."),
    ] = None,
    publish: Annotated[
        bool,
        typer.Option(
            "--publish/--no-publish",
            help="Also publish the versioned artifact after the quality gate.",
        ),
    ] = False,
    out: Annotated[
        Path,
        typer.Option("--out", help="Artifact output directory used with --publish."),
    ] = Path("dist-artifact"),
) -> None:
    """Acquire, load, transform, test, document, report and optionally publish."""

    def command() -> None:
        container = build_container(
            get_settings(),
            publish_out=out if publish else None,
        )
        try:
            report = container.pipeline.run(
                select=select or None,
                only=only,
                from_step=from_step,
            )
        finally:
            container.close()
        print_run(report)

    run_guarded(command)


def register(app: typer.Typer) -> None:
    """Attach the ``build`` command to the root Typer application."""
    app.command("build", help="Build the lakehouse through the full pipeline.")(build)
