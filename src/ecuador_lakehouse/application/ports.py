"""Application ports (``typing.Protocol``) implemented by adapters.

The application layer depends on these protocols only: no HTTP client, no
DuckDB, no dbt and no adapter import is allowed here (S17).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ecuador_lakehouse.domain.batches import BatchRecord, BatchStatus
from ecuador_lakehouse.domain.contract import ArtifactContract
from ecuador_lakehouse.domain.manifest import (
    ArtifactManifest,
    ArtifactVersion,
    QualityCounts,
    SourceRef,
)
from ecuador_lakehouse.domain.quality import QualitySummary
from ecuador_lakehouse.domain.report import ReportSnapshot
from ecuador_lakehouse.domain.runs import RunRecord
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

    def open(self) -> None:
        """(Re)open the warehouse after dbt had exclusive access to the file (D18)."""
        ...

    def close(self) -> None:
        """Flush and release the embedded database file."""
        ...


@runtime_checkable
class RunLedger(Protocol):
    """Repository for the pipeline run ledger ``meta.runs`` (S13)."""

    def record_run(self, record: RunRecord) -> None:
        """Persist one completed run and its step results."""
        ...

    def runs(self) -> tuple[RunRecord, ...]:
        """Return every recorded run, oldest first."""
        ...


@runtime_checkable
class Transformer(Protocol):
    """Run the dbt seed and transformation layers through one adapter (D4, D18)."""

    def seed_and_run(self, *, select: str | None = None) -> None:
        """Seed reference data and run every selected dbt model."""
        ...

    def test(self, *, select: str | None = None) -> QualitySummary:
        """Run selected dbt data and unit tests and return their summary."""
        ...

    def docs(self) -> Path:
        """Generate static dbt documentation and return the entry-point file."""
        ...

    def manifest(self) -> Mapping[str, Any]:
        """Return the dbt manifest produced by the last run."""
        ...

    def close(self) -> None:
        """Release any resources held by the transformer."""
        ...


@runtime_checkable
class LineageRenderer(Protocol):
    """Render a dbt manifest as human-readable lineage documentation (S12)."""

    def render_markdown(self, manifest: Mapping[str, Any]) -> str:
        """Return the complete Markdown document for ``manifest``."""
        ...


@runtime_checkable
class ReportReader(Protocol):
    """Read the marts and the dbt run results as one JSON-ready snapshot (S16)."""

    def read(self, *, mode: str) -> ReportSnapshot:
        """Query the warehouse read-only and return the aggregated report data."""
        ...


@runtime_checkable
class ReportRenderer(Protocol):
    """Render a snapshot as the self-contained static multi-page site (S16)."""

    def render(self, snapshot: ReportSnapshot, site_dir: Path) -> Path:
        """Write every page and asset under ``site_dir`` and return ``index.html``."""
        ...


@dataclass(frozen=True, slots=True)
class TableSpec:
    """Application-level metadata that completes the committed contract."""

    kind: str
    grain: str
    descriptions: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.kind not in {"dim", "fct", "mart"}:
            raise ValueError(f"unknown table kind: {self.kind!r}")
        if not self.grain.strip():
            raise ValueError("table grain must not be empty")
        descriptions = dict(self.descriptions)
        object.__setattr__(self, "descriptions", descriptions)
        if not descriptions:
            raise ValueError("table must describe at least one column")


@dataclass(frozen=True, slots=True)
class PublishRequest:
    """Everything the artifact adapter needs to publish one data product."""

    source_warehouse: Path
    out_dir: Path
    contract: ArtifactContract
    table_specs: Mapping[str, TableSpec]
    generator: str
    duckdb_version: str
    dbt_core_version: str
    data_mode: str
    built_from: tuple[SourceRef, ...]
    quality: QualityCounts
    attribution: str

    def __post_init__(self) -> None:
        if not self.generator.strip():
            raise ValueError("generator must not be empty")
        if not self.attribution.strip():
            raise ValueError("attribution must not be empty")
        if self.data_mode not in {"sample", "full"}:
            raise ValueError(f"unknown data mode: {self.data_mode!r}")
        specs = dict(self.table_specs)
        object.__setattr__(self, "table_specs", specs)
        expected = {table.name for table in self.contract.tables}
        missing = expected - set(specs)
        if missing:
            raise ValueError(f"missing table specs: {', '.join(sorted(missing))}")
        unexpected = set(specs) - expected
        if unexpected:
            raise ValueError(f"table specs for unknown tables: {', '.join(sorted(unexpected))}")


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Location and manifest of one published artifact."""

    artifact_dir: Path
    manifest: ArtifactManifest

    @property
    def table_count(self) -> int:
        """Number of published tables."""
        return len(self.manifest.tables)


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """Outcome of verifying one published artifact."""

    artifact_dir: Path
    table_count: int
    artifact_version: ArtifactVersion


@runtime_checkable
class ArtifactVerifier(Protocol):
    """Re-check a published artifact without needing a warehouse (S14)."""

    def verify(self, artifact_dir: Path) -> VerifyResult:
        """Re-check checksums, schemas and row counts of a published artifact."""
        ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Publish and verify the versioned data product (S14, D19)."""

    def publish(self, request: PublishRequest) -> PublishResult:
        """Write the complete artifact described by ``request``."""
        ...

    def verify(self, artifact_dir: Path) -> VerifyResult:
        """Re-check checksums, schemas and row counts of a published artifact."""
        ...

    def read_schema(self, warehouse_path: Path, *, base: ArtifactContract) -> ArtifactContract:
        """Read the warehouse ``marts`` schema using ``base`` for kind and grain."""
        ...
