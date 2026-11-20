"""Application ports (``typing.Protocol``) implemented by adapters.

The application layer depends on these protocols only: no HTTP client, no
DuckDB, no dbt and no adapter import is allowed here (S17).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ecuador_lakehouse.domain.batches import BatchRecord, BatchStatus
from ecuador_lakehouse.domain.sources import LicenseInfo, SourceFile, SourceId


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


@dataclass(frozen=True, slots=True)
class ParsedPartition:
    """A structurally extracted partition written as canonical UTF-8 CSV."""

    source_id: SourceId
    partition: str
    path: Path
    row_count: int

    def __post_init__(self) -> None:
        if not self.partition.strip():
            raise ValueError("partition must not be empty")
        if self.row_count < 0:
            raise ValueError(f"row_count must be non-negative: {self.row_count!r}")


@runtime_checkable
class SourceParser(Protocol):
    """Strategy that turns one upstream file into canonical CSV (D4, D5)."""

    source_id: SourceId

    def parse(
        self, path: Path, partition: str, *, output_dir: Path | None = None
    ) -> ParsedPartition:
        """Extract ``path`` into canonical UTF-8 CSV and report the row count."""
        ...


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


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Outcome of loading one canonical partition into the raw layer (S6)."""

    source_id: SourceId
    partition: str
    batch_id: str
    status: BatchStatus
    row_count: int


@runtime_checkable
class Warehouse(Protocol):
    """Raw-layer repository plus the one-transaction partition load (S6, D22)."""

    def load_partition(
        self,
        source_id: SourceId,
        partition: str,
        canonical_csv: Path,
        sha256: str,
        source_file: str,
    ) -> LoadResult:
        """Load a canonical CSV as one unit of work, skipping an identical vintage."""
        ...

    def ledger(self) -> tuple[BatchRecord, ...]:
        """Return the append-only batch ledger ordered by load time."""
        ...

    def close(self) -> None:
        """Flush and release the embedded database file."""
        ...
