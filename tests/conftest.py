"""Shared pytest fixtures.

The autouse fixture below enforces the project rule that tests never touch the
network: every socket connection to a non-loopback host fails loudly.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ecuador_lakehouse.adapters.sources.sample_fetcher import SampleSourceFetcher
from ecuador_lakehouse.config import get_settings
from ecuador_lakehouse.container import default_parsers, load_lockfile, load_sample_manifest
from ecuador_lakehouse.domain.sources import SourceId

NETWORK_BLOCK_MESSAGE = "Outbound network access is blocked in tests"


@dataclass(frozen=True, slots=True)
class CanonicalSample:
    """One bundled sample partition parsed into canonical CSV for warehouse tests."""

    source_id: SourceId
    partition: str
    path: Path
    sha256: str
    source_file: str
    rows: int


def _is_loopback(host: object) -> bool:
    if not isinstance(host, str):
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def block_non_loopback_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block DNS resolution and connections for every non-loopback host."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if not _is_loopback(host):
            raise RuntimeError(f"{NETWORK_BLOCK_MESSAGE}: {address!r}")
        return original_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        host = address[0] if isinstance(address, tuple) else address
        if not _is_loopback(host):
            raise RuntimeError(f"{NETWORK_BLOCK_MESSAGE}: {address!r}")
        return original_connect_ex(self, address)

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host is not None and not _is_loopback(host):
            raise RuntimeError(f"{NETWORK_BLOCK_MESSAGE}: {host!r}")
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture(autouse=True)
def reset_settings_cache() -> None:
    """Keep each test isolated from settings cached by a previous test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def canonical_sample(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[CanonicalSample, ...]:
    """Parse every bundled sample partition once for the warehouse test suite."""
    cache_dir = tmp_path_factory.mktemp("sample-cache")
    output_dir = tmp_path_factory.mktemp("canonical")
    fetcher = SampleSourceFetcher(load_sample_manifest(), cache_dir)
    parsers = default_parsers()
    entries: list[CanonicalSample] = []
    for source_file in load_lockfile().files:
        fetched = fetcher.fetch(source_file)
        parser = parsers[source_file.source_id]
        parsed = parser.parse(fetched.path, source_file.partition, output_dir=output_dir)
        entries.append(
            CanonicalSample(
                source_id=source_file.source_id,
                partition=source_file.partition,
                path=parsed.path,
                sha256=fetched.sha256,
                source_file=fetched.path.name,
                rows=parsed.row_count,
            )
        )
    return tuple(entries)
