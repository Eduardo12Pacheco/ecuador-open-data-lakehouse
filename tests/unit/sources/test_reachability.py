"""Tests for the optional source reachability probe used by ``doctor --network``."""

from __future__ import annotations

import httpx
import pytest

from ecuador_lakehouse.adapters.sources.reachability import (
    DEFAULT_HOSTS,
    HostProbe,
    probe_hosts,
    user_agent,
)


def test_every_allow_listed_host_is_probed() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(200, request=request)

    probes = probe_hosts(transport=httpx.MockTransport(handler))

    assert seen == list(DEFAULT_HOSTS)
    assert all(probe.ok for probe in probes)
    assert [probe.detail for probe in probes] == ["HTTP 200"] * 3


def test_server_error_marks_the_host_unreachable() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, request=request))

    probes = probe_hosts(("example.ec",), transport=transport)

    assert probes == (HostProbe("example.ec", False, "HTTP 503 (server error)"),)


def test_client_error_still_counts_as_reachable() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(403, request=request))

    probes = probe_hosts(("example.ec",), transport=transport)

    assert probes[0].ok is True
    assert probes[0].detail == "HTTP 403"


def test_transport_error_marks_the_host_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    probes = probe_hosts(("example.ec",), transport=httpx.MockTransport(handler))

    assert probes[0].ok is False
    assert probes[0].detail == "ConnectError"


def test_user_agent_is_honest() -> None:
    assert user_agent().startswith("ecuador-open-data-lakehouse/")


@pytest.mark.parametrize("timeout_s", [0, -1, 61])
def test_invalid_timeout_is_rejected(timeout_s: float) -> None:
    with pytest.raises(ValueError, match="timeout_s"):
        probe_hosts(("example.ec",), timeout_s=timeout_s)
