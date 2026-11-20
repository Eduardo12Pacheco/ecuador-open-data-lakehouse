"""``lakehouse fetch`` command: acquire pinned upstream files (S4)."""

from __future__ import annotations

import typer

from ecuador_lakehouse.application.ports import FetchResult
from ecuador_lakehouse.config import Settings, get_settings, parse_years
from ecuador_lakehouse.container import build_container
from ecuador_lakehouse.domain.errors import ConfigError, LakehouseError
from ecuador_lakehouse.domain.sources import SourceId

_SOURCE_ALIASES: dict[str, SourceId] = {
    "sri": SourceId.SRI_TAX,
    "sri_tax": SourceId.SRI_TAX,
    "bce": SourceId.BCE_CNT,
    "bce_cnt": SourceId.BCE_CNT,
    "inec": SourceId.INEC_CPI,
    "inec_cpi": SourceId.INEC_CPI,
}


def _resolve_source(raw: str) -> SourceId:
    source = _SOURCE_ALIASES.get(raw.strip().lower())
    if source is None:
        choices = ", ".join(sorted({"sri", "bce", "inec"}))
        raise ConfigError(f"unknown source {raw!r} (choose from {choices})")
    return source


def _selected_partitions(
    source_id: SourceId, years: str | None, settings: Settings
) -> tuple[str, ...] | None:
    if years is not None:
        if source_id is not SourceId.SRI_TAX:
            raise ConfigError("--years only applies to --source sri")
        try:
            parsed = parse_years(years)
        except ValueError as exc:
            raise ConfigError(f"invalid --years value {years!r}: {exc}") from exc
        return tuple(str(year) for year in parsed)
    if source_id is SourceId.SRI_TAX:
        return tuple(str(year) for year in settings.years)
    return None


def _describe(result: FetchResult) -> str:
    origin = "cached" if result.from_cache else "downloaded"
    if result.checksum_verified:
        status = "sha256 OK"
    else:
        status = "sha256 UNVERIFIED (mutable vintage not accepted)"
    return (
        f"{status} {result.sha256[:8]} {result.source_file.filename} "
        f"({result.size_bytes} bytes, {origin})"
    )


def fetch(
    source: str = typer.Option(
        ...,
        "--source",
        help="Source to fetch: sri, bce or inec.",
    ),
    years: str | None = typer.Option(
        None,
        "--years",
        help="SRI years to fetch, e.g. 2024 or 2019,2021-2022 (default: LAKEHOUSE_YEARS).",
    ),
    accept_new_vintage: bool = typer.Option(
        False,
        "--accept-new-vintage",
        help="Record a changed checksum for a mutable source (for example the current SRI year).",
    ),
) -> None:
    """Download pinned upstream files, verify their SHA-256 checksums and cache them."""
    container = None
    try:
        settings = get_settings()
        source_id = _resolve_source(source)
        partitions = _selected_partitions(source_id, years, settings)
        container = build_container(settings)
        results = container.acquire_sources.execute(
            source_id,
            partitions,
            accept_new_vintage=accept_new_vintage,
        )
    except LakehouseError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=error.exit_code) from None
    finally:
        if container is not None:
            container.close()

    if not results:
        typer.echo("No pinned files selected.")
        raise typer.Exit(code=0)
    for result in results:
        typer.echo(_describe(result))
        if result.new_vintage:
            typer.echo(
                f"Recorded new vintage for {result.source_file.source_id.value}/"
                f"{result.source_file.partition}: {result.sha256}"
            )
    typer.echo(f"Fetched {len(results)} file(s).")


def register(app: typer.Typer) -> None:
    """Attach the ``fetch`` command to the root Typer application."""
    app.command("fetch", help="Download and verify pinned upstream source files.")(fetch)
