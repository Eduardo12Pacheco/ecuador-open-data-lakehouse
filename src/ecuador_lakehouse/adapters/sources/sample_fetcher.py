"""Fetcher strategy that serves the bundled offline sample (S2, S3).

The sample is a first-class, checksum-verified source: every bundled file is
listed in ``SAMPLE_MANIFEST.json`` and copied into the cache before use, so the
rest of the pipeline is identical in ``sample`` and ``full`` modes.
"""

from __future__ import annotations

import hashlib
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from ecuador_lakehouse.application.ports import FetchResult
from ecuador_lakehouse.domain.errors import ChecksumMismatchError, ConfigError
from ecuador_lakehouse.domain.sample import SampleFile, SampleManifest
from ecuador_lakehouse.domain.sources import SourceFile

MANIFEST_NAME = "SAMPLE_MANIFEST.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _packaged_sample_dir() -> Traversable:
    return resources.files("ecuador_lakehouse").joinpath("sample_data")


class SampleSourceFetcher:
    """Read bundled files from package resources, verify them and cache a copy."""

    def __init__(
        self,
        manifest: SampleManifest,
        cache_dir: Path,
        *,
        data_dir: Path | None = None,
    ) -> None:
        self._manifest = manifest
        self._cache_root = cache_dir
        self._data_dir = data_dir
        self._by_partition = {(entry.source_id, entry.partition): entry for entry in manifest.files}

    @staticmethod
    def load_manifest(data_dir: Path | None = None) -> SampleManifest:
        """Load the packaged (or overridden) sample manifest."""
        try:
            if data_dir is not None:
                text = (data_dir / MANIFEST_NAME).read_text(encoding="utf-8")
            else:
                text = _packaged_sample_dir().joinpath(MANIFEST_NAME).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise ConfigError("bundled sample manifest is missing or unreadable") from exc
        return SampleManifest.from_json_text(text)

    def fetch(self, source_file: SourceFile, *, accept_new_vintage: bool = False) -> FetchResult:
        """Copy one bundled sample file into the cache after verifying its checksum."""
        del accept_new_vintage  # the sample is immutable by construction
        entry = self._by_partition.get((source_file.source_id, source_file.partition))
        if entry is None:
            raise ConfigError(
                f"sample file not bundled for {source_file.source_id.value}/{source_file.partition}"
            )
        target = self._cache_root / entry.source_id.value / entry.name
        if target.exists():
            cached = target.read_bytes()
            if _sha256(cached) == entry.sha256 and len(cached) == entry.size_bytes:
                return self._result(source_file, entry, target, from_cache=True)
        payload = self._read_sample(entry)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return self._result(source_file, entry, target, from_cache=False)

    def verify_all(self) -> int:
        """Verify every bundled file against the manifest and return the count."""
        for entry in self._manifest.files:
            self._read_sample(entry)
        return len(self._manifest.files)

    def close(self) -> None:
        """No network or file handles are held between calls."""

    def _read_sample(self, entry: SampleFile) -> bytes:
        try:
            if self._data_dir is not None:
                payload = (self._data_dir / entry.name).read_bytes()
            else:
                payload = _packaged_sample_dir().joinpath(entry.name).read_bytes()
        except (FileNotFoundError, OSError) as exc:
            raise ConfigError(f"bundled sample file is missing: {entry.name}") from exc
        actual = _sha256(payload)
        if actual != entry.sha256 or len(payload) != entry.size_bytes:
            raise ChecksumMismatchError(
                f"checksum mismatch for bundled sample {entry.name}: "
                f"expected {entry.sha256} ({entry.size_bytes} bytes), "
                f"got {actual} ({len(payload)} bytes)"
            )
        return payload

    @staticmethod
    def _result(
        source_file: SourceFile,
        entry: SampleFile,
        path: Path,
        *,
        from_cache: bool,
    ) -> FetchResult:
        return FetchResult(
            source_file=source_file,
            path=path,
            sha256=entry.sha256,
            size_bytes=entry.size_bytes,
            from_cache=from_cache,
            checksum_verified=True,
        )
