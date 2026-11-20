"""Behaviour tests for the resumable streaming downloader (S4, S21).

All requests go through ``httpx.MockTransport``; the autouse socket-block
fixture guarantees no test can silently reach the real network.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from ecuador_lakehouse.adapters.sources.download import (
    DEFAULT_ALLOWED_HOSTS,
    StreamingDownloader,
)
from ecuador_lakehouse.domain.errors import SourceUnavailableError

BODY = b"ANIO|MES|VALOR\n2024|01 Enero|83,31\n"
URL = "https://descargas.sri.gob.ec/download/datosAbiertos/sri_recaudacion_2024.csv"


def make_downloader(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: object,
) -> StreamingDownloader:
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return StreamingDownloader(
        client,
        sleep=lambda _seconds: None,
        allowed_hosts=DEFAULT_ALLOWED_HOSTS,
        **kwargs,  # type: ignore[arg-type]
    )


def partial_path(tmp_path: Path) -> Path:
    directory = tmp_path / "cache"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "download.part"


def test_download_writes_the_complete_body(tmp_path: Path) -> None:
    downloader = make_downloader(tmp_path, lambda _request: httpx.Response(200, content=BODY))
    partial = partial_path(tmp_path)

    downloader.download(URL, partial)

    assert partial.read_bytes() == BODY


def test_download_resumes_a_truncated_part_file(tmp_path: Path) -> None:
    partial = partial_path(tmp_path)
    partial.write_bytes(BODY[:10])
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            206,
            content=BODY[10:],
            headers={
                "Content-Length": str(len(BODY) - 10),
                "Content-Range": f"bytes 10-{len(BODY) - 1}/{len(BODY)}",
            },
        )

    make_downloader(tmp_path, handler).download(URL, partial)

    assert seen[0].headers["Range"] == "bytes=10-"
    assert partial.read_bytes() == BODY


def test_download_restarts_when_the_server_ignores_the_range_header(tmp_path: Path) -> None:
    partial = partial_path(tmp_path)
    partial.write_bytes(BODY[:10])
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=BODY)

    make_downloader(tmp_path, handler).download(URL, partial)

    assert "Range" in seen[0].headers
    assert partial.read_bytes() == BODY


def test_a_416_restarts_the_download_from_scratch(tmp_path: Path) -> None:
    partial = partial_path(tmp_path)
    partial.write_bytes(BODY + b"stale")
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            return httpx.Response(416)
        assert "Range" not in request.headers
        return httpx.Response(200, content=BODY)

    make_downloader(tmp_path, handler, retries=1).download(URL, partial)

    assert partial.read_bytes() == BODY
    assert len(calls) == 2


def test_transport_errors_are_retried_with_exponential_backoff(tmp_path: Path) -> None:
    calls: list[int] = []
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, content=BODY)

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    downloader = StreamingDownloader(
        client,
        retries=2,
        sleep=delays.append,
        allowed_hosts=DEFAULT_ALLOWED_HOSTS,
    )

    downloader.download(URL, partial_path(tmp_path))

    assert len(calls) == 3
    assert delays == [0.5, 1.0]


def test_exhausted_retries_raise_source_unavailable(tmp_path: Path) -> None:
    calls: list[int] = []
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(len(calls) + 1)
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    downloader = StreamingDownloader(
        client,
        retries=1,
        sleep=delays.append,
        allowed_hosts=DEFAULT_ALLOWED_HOSTS,
    )

    with pytest.raises(SourceUnavailableError, match="failed to download") as excinfo:
        downloader.download(URL, partial_path(tmp_path))

    assert excinfo.value.exit_code == 5
    assert len(calls) == 2
    assert len(delays) == 1


def test_http_5xx_is_retried(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=BODY)

    make_downloader(tmp_path, handler, retries=1).download(URL, partial_path(tmp_path))

    assert len(calls) == 2


def test_a_non_retryable_4xx_raises_source_unavailable(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(len(calls) + 1)
        return httpx.Response(404)

    with pytest.raises(SourceUnavailableError, match="404"):
        make_downloader(tmp_path, handler, retries=3).download(URL, partial_path(tmp_path))

    assert len(calls) == 1


def test_an_oversize_download_is_refused(tmp_path: Path) -> None:
    downloader = make_downloader(
        tmp_path,
        lambda _request: httpx.Response(200, content=BODY),
        max_bytes=len(BODY) - 1,
    )

    with pytest.raises(SourceUnavailableError, match="size cap"):
        downloader.download(URL, partial_path(tmp_path))


def test_an_oversize_content_length_is_refused_before_streaming(tmp_path: Path) -> None:
    downloader = make_downloader(
        tmp_path,
        lambda _request: httpx.Response(200, content=BODY, headers={"Content-Length": str(10_000)}),
        max_bytes=100,
    )

    with pytest.raises(SourceUnavailableError, match="size cap"):
        downloader.download(URL, partial_path(tmp_path))


def test_a_redirect_to_a_host_outside_the_allow_list_is_refused(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.example/steal.csv"})

    with pytest.raises(SourceUnavailableError, match="allow-list"):
        make_downloader(tmp_path, handler).download(URL, partial_path(tmp_path))

    assert len(seen) == 1


def test_a_redirect_inside_the_allow_list_is_followed(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/download/datosAbiertos/sri_recaudacion_2024.csv":
            return httpx.Response(302, headers={"Location": "/moved/sri_recaudacion_2024.csv"})
        return httpx.Response(200, content=BODY)

    partial = partial_path(tmp_path)
    make_downloader(tmp_path, handler).download(URL, partial)

    assert partial.read_bytes() == BODY


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/data.csv",
        "http://descargas.sri.gob.ec/download/datosAbiertos/sri_recaudacion_2024.csv",
        "https://descargas.sri.gob.ec:8443/download/datosAbiertos/sri_recaudacion_2024.csv",
    ],
)
def test_only_https_default_ports_on_allowed_hosts_are_accepted(tmp_path: Path, url: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=BODY)

    with pytest.raises(SourceUnavailableError, match="allow-list"):
        make_downloader(tmp_path, handler).download(url, partial_path(tmp_path))

    assert seen == []
