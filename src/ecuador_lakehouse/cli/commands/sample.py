"""``lakehouse sample`` maintainer command: rebuild the bundled offline sample (S3)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ecuador_lakehouse.config import get_settings, parse_years
from ecuador_lakehouse.container import build_sample_builder
from ecuador_lakehouse.domain.errors import ConfigError, LakehouseError

sample_app = typer.Typer(
    name="sample",
    help="Maintainer commands for the bundled offline sample.",
    no_args_is_help=True,
)


def build(
    years: Annotated[
        str | None,
        typer.Option(
            "--years",
            help="SRI years to bundle, e.g. 2024 or 2019,2021-2022 (default: LAKEHOUSE_YEARS).",
        ),
    ] = None,
    cache_dir: Annotated[
        Path | None,
        typer.Option(
            "--cache-dir",
            help="Directory for the downloaded upstream files (default: $LAKEHOUSE_HOME/cache).",
        ),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            help="Where to write the sample files (default: the packaged sample_data directory).",
        ),
    ] = None,
    seed_dir: Annotated[
        Path | None,
        typer.Option(
            "--seed-dir",
            help="Where to write control_totals.csv (default: the packaged seeds directory).",
        ),
    ] = None,
) -> None:
    """Download the pinned sources and regenerate the bundled, offline sample."""
    builder = None
    try:
        settings = get_settings()
        try:
            selected = parse_years(years) if years is not None else settings.years
        except ValueError as error:
            raise ConfigError(f"invalid --years value {years!r}: {error}") from error
        builder = build_sample_builder(
            settings,
            cache_dir=cache_dir,
            output_dir=output_dir,
            seed_dir=seed_dir,
        )
        report = builder.execute(selected)
    except LakehouseError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=error.exit_code) from None
    finally:
        if builder is not None:
            builder.fetcher.close()

    for entry in report.files:
        origin = "cached" if report.is_cached(entry.name) else "downloaded"
        typer.echo(
            f"sha256 OK {entry.sha256[:8]} {entry.name} "
            f"({entry.size_bytes} bytes, {origin}, {entry.rows} rows)"
        )
    typer.echo(f"Wrote {len(report.files)} sample files ({report.total_bytes} bytes).")
    typer.echo(f"Control totals: {len(report.control_totals)} SRI rows.")


def register(app: typer.Typer) -> None:
    """Attach the ``sample`` command group to the root Typer application."""
    sample_app.command("build", help="Regenerate the bundled offline sample.")(build)
    app.add_typer(sample_app, name="sample")
