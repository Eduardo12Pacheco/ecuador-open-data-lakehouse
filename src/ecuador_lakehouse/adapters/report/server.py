"""Loopback-only static server for the generated report site (S16).

The site is plain HTML/CSS/JS, so ``http.server`` is enough: no framework, no
extra install and no remote requests. Only loopback addresses are accepted and
the handler serves exclusively from the generated ``site/`` directory.
"""

from __future__ import annotations

import ipaddress
import logging
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ecuador_lakehouse.domain.errors import ConfigError

logger = logging.getLogger(__name__)

_LOOPBACK_NAMES = frozenset({"localhost"})


def is_loopback_host(host: str) -> bool:
    """Return True when ``host`` names this machine's loopback interface."""
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class ReportRequestHandler(SimpleHTTPRequestHandler):
    """Serve files under the report directory with sensible cache headers."""

    server_version = "EcuadorLakehouseReport/1.0"

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        logger.info("%s - %s", self.address_string(), format % args)


class ReportHTTPServer(ThreadingHTTPServer):
    """Threaded server that never keeps a request thread alive at shutdown."""

    daemon_threads = True
    allow_reuse_address = True


def create_server(
    site_dir: Path, *, host: str = "127.0.0.1", port: int = 15080
) -> ReportHTTPServer:
    """Bind a loopback report server for ``site_dir`` and return it unstarted."""
    if not is_loopback_host(host):
        raise ConfigError(
            f"the report server only binds loopback addresses, refusing host {host!r}"
        )
    site = Path(site_dir)
    if not (site / "index.html").is_file():
        raise ConfigError(f"report site not found at {site}; run: lakehouse build")
    handler = partial(ReportRequestHandler, directory=str(site))
    try:
        return ReportHTTPServer((host, port), handler)
    except OSError as exc:
        raise ConfigError(f"cannot bind {host}:{port}: {exc}") from exc


def server_url(server: ReportHTTPServer) -> str:
    """Return the base URL of a bound server."""
    host, port = server.server_address[:2]
    display_host = str(host)
    if isinstance(host, str) and not is_loopback_host(host):
        display_host = "127.0.0.1"
    return f"http://{display_host}:{port}"


def host_for_display(host: str) -> str:
    """Resolve ``localhost`` to a printable loopback address."""
    if host == "localhost":
        return "127.0.0.1"
    return host
