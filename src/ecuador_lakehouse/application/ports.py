"""Application ports (``typing.Protocol``) implemented by adapters.

The application layer depends on these protocols only: no HTTP client, no
DuckDB, no dbt and no adapter import is allowed here (S17).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ecuador_lakehouse.domain.sources import LicenseInfo, SourceFile


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Outcome of acquiring one pinned source file into the local cache."""

    source_file: SourceFile
    path: Path
    sha256: str
    size_bytes: int
    from_cache: bool
    checksum_verified: bool
    new_vintage: bool = False


@runtime_checkable
class SourceFetcher(Protocol):
    """Acquire one pinned file and verify its content (Strategy by mode)."""

    def fetch(self, source_file: SourceFile, *, accept_new_vintage: bool = False) -> FetchResult:
        """Download ``source_file`` into the cache and return the verified result."""
        ...

    def close(self) -> None:
        """Release any network or file resources held by the fetcher."""
        ...


@runtime_checkable
class LicenseCatalog(Protocol):
    """Read dataset license metadata from the open-data catalogue."""

    def package_show(self, dataset_id: str) -> LicenseInfo:
        """Return the license information recorded by CKAN for ``dataset_id``."""
        ...

    def close(self) -> None:
        """Release any network resources held by the catalogue adapter."""
        ...
