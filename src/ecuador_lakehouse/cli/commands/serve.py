"""``lakehouse serve`` command: serve the generated static report (S16)."""

from __future__ import annotations

import webbrowser
from typing import Annotated

import typer

from ecuador_lakehouse.adapters.report.server import create_server, server_url
from ecuador_lakehouse.cli.guard import run_guarded
from ecuador_lakehouse.config import get_settings
from ecuador_lakehouse.container import build_container
from ecuador_lakehouse.domain.errors import ConfigError

_MAX_PORT = 65535


def serve(
    host: Annotated[
        str | None,
        typer.Option("--host", help="Loopback address to bind (defaults to settings)."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Port to bind (defaults to settings, 15080)."),
    ] = None,
    open_browser: Annotated[
        bool,
        typer.Option("--open/--no-open", help="Open the report in the default browser."),
    ] = True,
) -> None:
    """Serve the report site on loopback, building it first when missing."""

    def command() -> None:
        settings = get_settings()
        warehouse = settings.home / "warehouse.duckdb"
        if not warehouse.is_file():
            raise ConfigError("No data yet - run: lakehouse build")
        site = settings.home / "site"
        if not (site / "index.html").is_file():
            container = build_container(settings)
            try:
                result = container.build_report.execute()
            finally:
                container.close()
            typer.echo(f"report: {result.page_count} pages written to {site}")

        resolved_host = host if host is not None else settings.serve_host
        resolved_port = port if port is not None else settings.serve_port
        if not 0 <= resolved_port <= _MAX_PORT:
            raise ConfigError(f"invalid port: {resolved_port}")
        server = create_server(site, host=resolved_host, port=resolved_port)
        url = server_url(server)
        typer.echo(f"Serving {site} at {url} (Ctrl+C to stop)")
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            typer.echo("Stopped.")
        finally:
            server.server_close()

    run_guarded(command)


def register(app: typer.Typer) -> None:
    """Attach the ``serve`` command to the root Typer application."""
    app.command("serve", help="Serve the static report site on loopback.")(serve)
