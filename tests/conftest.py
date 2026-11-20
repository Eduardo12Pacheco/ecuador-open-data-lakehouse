"""Shared pytest fixtures.

The autouse fixture below enforces the project rule that tests never touch the
network: every socket connection to a non-loopback host fails loudly.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

import pytest

NETWORK_BLOCK_MESSAGE = "Outbound network access is blocked in tests"


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
