"""Resumable, retrying, size-capped streaming HTTP transfers (S4, S21).

This module only moves bytes: it does not know about checksums, partitions or
the vintage ledger. Redirects are followed manually because
``httpx``'s ``follow_redirects=True`` would happily leave the host allow-list.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from ecuador_lakehouse.domain.errors import SourceUnavailableError

DEFAULT_MAX_BYTES = 300 * 1024 * 1024
DEFAULT_ALLOWED_HOSTS = frozenset(
    {
        "descargas.sri.gob.ec",
        "www.ecuadorencifras.gob.ec",
        "www.datosabiertos.gob.ec",
        "datosabiertos.gob.ec",
    }
)
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_REDIRECTS = 5
_BACKOFF_BASE_S = 0.5
_BACKOFF_CAP_S = 8.0
_READ_CHUNK = 1024 * 1024
_HTTP_OK = 200
_HTTP_PARTIAL = 206
_HTTP_RANGE_NOT_SATISFIABLE = 416


class _RetryableFailureError(Exception):
    """Internal signal that the transfer may succeed on a later attempt."""


class StreamingDownloader:
    """Download one URL into a ``.part`` file with resume, retries and caps."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        retries: int = 3,
        max_bytes: int = DEFAULT_MAX_BYTES,
        sleep: Callable[[float], None] = time.sleep,
        allowed_hosts: frozenset[str],
    ) -> None:
        if retries < 0:
            raise ValueError(f"retries must be non-negative: {retries!r}")
        if max_bytes <= 0:
            raise ValueError(f"max_bytes must be positive: {max_bytes!r}")
        if not allowed_hosts:
            raise ValueError("allowed_hosts must not be empty")
        self._client = client
        self._retries = retries
        self._max_bytes = max_bytes
        self._sleep = sleep
        self._allowed_hosts = allowed_hosts

    def validate_url(self, url: str) -> None:
        """Reject URLs whose scheme, host or port is outside the allow-list."""
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or host not in self._allowed_hosts:
            raise SourceUnavailableError(f"URL host is not in the download allow-list: {url}")
        if parsed.username or parsed.password:
            raise SourceUnavailableError(f"URL must not embed credentials: {url}")
        try:
            port = parsed.port
        except ValueError as exc:
            raise SourceUnavailableError(f"URL has an invalid port: {url}") from exc
        if port not in (None, 443):
            raise SourceUnavailableError(f"URL host is not in the download allow-list: {url}")

    def download(self, url: str, partial: Path) -> None:
        """Download ``url`` to ``partial``, resuming a previous partial file."""
        self.validate_url(url)
        last_error: _RetryableFailureError | None = None
        for attempt in range(self._retries + 1):
            try:
                self._download_once(url, partial)
                return
            except _RetryableFailureError as exc:
                last_error = exc
                if attempt >= self._retries:
                    break
                self._sleep(min(_BACKOFF_BASE_S * 2**attempt, _BACKOFF_CAP_S))
        raise SourceUnavailableError(f"failed to download {url}: {last_error}") from last_error

    def _download_once(self, url: str, partial: Path) -> None:  # noqa: PLR0912
        start = partial.stat().st_size if partial.exists() else 0
        request_headers = {"Range": f"bytes={start}-"} if start else {}
        current_url = url
        redirects = 0

        while True:
            request = self._client.build_request("GET", current_url, headers=request_headers)
            try:
                response = self._client.send(request, stream=True)
            except httpx.TransportError as exc:
                raise _RetryableFailureError(str(exc)) from exc
            try:
                if response.status_code in _REDIRECT_STATUSES:
                    if redirects >= _MAX_REDIRECTS:
                        raise SourceUnavailableError(f"too many redirects while downloading {url}")
                    location = response.headers.get("location")
                    if not location:
                        raise SourceUnavailableError(
                            f"redirect without Location from {current_url}"
                        )
                    next_url = urljoin(str(response.url), location)
                    self.validate_url(next_url)
                    current_url = next_url
                    redirects += 1
                    continue

                if response.status_code == _HTTP_RANGE_NOT_SATISFIABLE and start > 0:
                    # A stale or over-long partial file: drop it and restart.
                    partial.unlink(missing_ok=True)
                    raise _RetryableFailureError("HTTP 416; restarting the download from scratch")

                if response.status_code == _HTTP_OK:
                    mode = "wb"
                    start = 0
                elif response.status_code == _HTTP_PARTIAL:
                    mode = "ab" if start > 0 else "wb"
                elif response.status_code in _RETRYABLE_STATUSES:
                    raise _RetryableFailureError(f"HTTP {response.status_code}")
                else:
                    raise SourceUnavailableError(
                        f"HTTP {response.status_code} while downloading {current_url}"
                    )

                self._check_declared_size(response, start)
                total = start
                with partial.open(mode) as sink:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self._max_bytes:
                            raise SourceUnavailableError(
                                f"file exceeds the {self._max_bytes}-byte size cap: {current_url}"
                            )
                        sink.write(chunk)
                return
            finally:
                response.close()

    def _check_declared_size(self, response: httpx.Response, start: int) -> None:
        content_length = response.headers.get("content-length")
        if content_length is None:
            return
        try:
            remaining = int(content_length)
        except ValueError:
            return
        if remaining < 0:
            return
        if start + remaining > self._max_bytes:
            raise SourceUnavailableError(
                f"file exceeds the {self._max_bytes}-byte size cap: {response.url}"
            )
