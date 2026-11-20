"""Checksum-verified HTTP source fetcher (S4, S21).

The fetcher composes two collaborators: :class:`StreamingDownloader` moves the
bytes safely, :class:`VintageLedger` remembers explicitly accepted checksums
for mutable sources. Immutable checksum mismatches always raise exit code 3.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import structlog

from ecuador_lakehouse import __version__
from ecuador_lakehouse.adapters.sources.download import (
    DEFAULT_ALLOWED_HOSTS,
    DEFAULT_MAX_BYTES,
    StreamingDownloader,
)
from ecuador_lakehouse.adapters.sources.vintage import VintageLedger
from ecuador_lakehouse.application.ports import FetchResult
from ecuador_lakehouse.domain.errors import ChecksumMismatchError
from ecuador_lakehouse.domain.sources import SourceFile

_USER_AGENT = f"ecuador-open-data-lakehouse/{__version__}"
_READ_CHUNK = 1024 * 1024

_log = structlog.get_logger(__name__)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class HttpSourceFetcher:
    """Download pinned upstream files with resume, retries and verification."""

    def __init__(  # noqa: PLR0913 - explicit, testable transport options
        self,
        home: Path,
        *,
        cache_dir: Path | None = None,
        timeout_s: float = 30.0,
        retries: int = 3,
        max_bytes: int = DEFAULT_MAX_BYTES,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        allowed_hosts: frozenset[str] = DEFAULT_ALLOWED_HOSTS,
    ) -> None:
        self._cache_root = cache_dir if cache_dir is not None else home / "cache"
        self._ledger = VintageLedger(self._cache_root)
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=False,
            headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "identity"},
        )
        self._downloader = StreamingDownloader(
            self._client,
            retries=retries,
            max_bytes=max_bytes,
            sleep=sleep,
            allowed_hosts=allowed_hosts,
        )

    def fetch(self, source_file: SourceFile, *, accept_new_vintage: bool = False) -> FetchResult:
        """Download, verify and cache ``source_file``; return the verified result."""
        self._downloader.validate_url(source_file.url)
        target = self._cache_root / source_file.source_id.value / source_file.filename
        partial = target.with_name(f"{target.name}.part")
        target.parent.mkdir(parents=True, exist_ok=True)

        cached = self._cached_result(source_file, target)
        if cached is not None:
            return cached

        self._downloader.download(source_file.url, partial)
        actual_sha = _sha256_file(partial)
        actual_size = partial.stat().st_size
        if actual_sha == source_file.sha256:
            partial.replace(target)
            return self._result(source_file, target, actual_sha, from_cache=False, verified=True)
        if not source_file.mutable:
            partial.unlink(missing_ok=True)
            raise ChecksumMismatchError(
                f"checksum mismatch for {source_file.filename}: "
                f"expected {source_file.sha256}, got {actual_sha}"
            )

        if accept_new_vintage:
            self._ledger.record(source_file, actual_sha, actual_size)
        _log.warning(
            "mutable source checksum differs from the pinned vintage",
            file=source_file.filename,
            expected=source_file.sha256,
            actual=actual_sha,
            accepted=accept_new_vintage,
        )
        partial.replace(target)
        return self._result(
            source_file,
            target,
            actual_sha,
            from_cache=False,
            verified=accept_new_vintage,
            new_vintage=accept_new_vintage,
            size_bytes=actual_size,
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def _cached_result(self, source_file: SourceFile, target: Path) -> FetchResult | None:
        if not target.exists():
            return None
        actual_sha = _sha256_file(target)
        if actual_sha == source_file.sha256:
            return self._result(source_file, target, actual_sha, from_cache=True, verified=True)
        if source_file.mutable and self._ledger.accepted_sha(source_file) == actual_sha:
            return self._result(source_file, target, actual_sha, from_cache=True, verified=True)
        target.unlink()
        target.with_name(f"{target.name}.part").unlink(missing_ok=True)
        return None

    @staticmethod
    def _result(  # noqa: PLR0913 - one cohesive value object
        source_file: SourceFile,
        path: Path,
        sha256: str,
        *,
        from_cache: bool,
        verified: bool,
        new_vintage: bool = False,
        size_bytes: int | None = None,
    ) -> FetchResult:
        return FetchResult(
            source_file=source_file,
            path=path,
            sha256=sha256,
            size_bytes=size_bytes if size_bytes is not None else path.stat().st_size,
            from_cache=from_cache,
            checksum_verified=verified,
            new_vintage=new_vintage,
        )
