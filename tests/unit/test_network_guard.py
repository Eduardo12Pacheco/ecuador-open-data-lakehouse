"""Tests for the autouse network guard fixture."""

from __future__ import annotations

import socket

import pytest
from tests.conftest import NETWORK_BLOCK_MESSAGE


def test_non_loopback_connection_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=NETWORK_BLOCK_MESSAGE):
        socket.create_connection(("example.com", 80), timeout=0.1)


def test_non_loopback_dns_resolution_is_blocked() -> None:
    with pytest.raises(RuntimeError, match=NETWORK_BLOCK_MESSAGE):
        socket.getaddrinfo("example.com", 443)


def test_loopback_connection_is_allowed() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        address = server.getsockname()

        with socket.create_connection(address, timeout=1.0) as client:
            assert client.getpeername()[0] == "127.0.0.1"
