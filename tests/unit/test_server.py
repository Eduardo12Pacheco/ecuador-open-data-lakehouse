"""Unit tests for the loopback-only static report server (S16)."""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.report.server import create_server
from ecuador_lakehouse.domain.errors import ConfigError


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    (site / "index.html").write_text("<!doctype html><h1>Overview</h1>", encoding="utf-8")
    (site / "tax.html").write_text("<!doctype html><h1>Tax</h1>", encoding="utf-8")
    (site / "assets" / "app.css").write_text("body{color:#111}", encoding="utf-8")
    return site


@pytest.fixture
def served(tmp_path: Path):
    server = create_server(_site(tmp_path), host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url: str) -> tuple[int, str, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - loopback only
            content_type = response.headers.get("Content-Type", "")
            return response.status, content_type, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("Content-Type", ""), error.read().decode()


def test_server_binds_loopback_only(tmp_path: Path) -> None:
    server = create_server(_site(tmp_path), host="127.0.0.1", port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
    finally:
        server.server_close()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])  # noqa: S104
def test_non_loopback_hosts_are_rejected(tmp_path: Path, host: str) -> None:
    with pytest.raises(ConfigError, match="loopback"):
        create_server(_site(tmp_path), host=host, port=0)


def test_existing_site_is_required(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="report site"):
        create_server(tmp_path / "missing", host="127.0.0.1", port=0)


def test_serves_index_and_local_assets(served: str) -> None:
    status, content_type, body = _get(f"{served}/")
    assert status == 200
    assert content_type.startswith("text/html")
    assert "Overview" in body

    status, _, tax = _get(f"{served}/tax.html")
    assert status == 200
    assert "Tax" in tax

    status, content_type, css = _get(f"{served}/assets/app.css")
    assert status == 200
    assert content_type.startswith("text/css")
    assert "body" in css


def test_unknown_path_returns_404(served: str) -> None:
    status, _, body = _get(f"{served}/nope.html")
    assert status == 404
    assert "not found" in body.lower()


def test_path_traversal_cannot_escape_the_site(served: str) -> None:
    status, _, _ = _get(f"{served}/%2e%2e/%2e%2e/etc/passwd")
    assert status in {400, 404}
