"""Build-report use case: write the static multi-page site from the marts (S16).

The application orchestrates two ports only: a read-only report reader that
returns a JSON-ready snapshot and a renderer that writes the self-contained
site. The DuckDB write connection is closed while the reader runs (a second
connection cannot share the file) and reopened afterwards so the pipeline keeps
working if another step is selected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ecuador_lakehouse.application.ports import ReportReader, ReportRenderer, Warehouse
from ecuador_lakehouse.domain.report import ReportSnapshot
from ecuador_lakehouse.domain.sources import Lockfile

PAGE_COUNT = 7


@dataclass(frozen=True, slots=True)
class ReportResult:
    """Paths and counts produced by one report run."""

    path: Path
    batch_count: int
    page_count: int = PAGE_COUNT


def source_inventory(lockfile: Lockfile) -> tuple[dict[str, object], ...]:
    """Flatten the lockfile into the rows rendered by the sources page."""
    return tuple(
        {
            "source_id": source_file.source_id.value,
            "partition": source_file.partition,
            "filename": source_file.filename,
            "url": source_file.url,
            "bytes": source_file.size_bytes,
            "sha256": source_file.sha256,
            "mutable": source_file.mutable,
            "encoding_hint": source_file.encoding_hint or "",
            "license_id": lockfile.licenses.get(source_file.source_id.value, ""),
        }
        for source_file in lockfile.files
    )


class BuildReport:
    """Query the marts through the reader port and render every report page."""

    def __init__(  # noqa: PLR0913 - dependency injection needs every collaborator
        self,
        *,
        warehouse: Warehouse,
        reader: ReportReader,
        renderer: ReportRenderer,
        lockfile: Lockfile,
        site_dir: Path,
        mode: str,
    ) -> None:
        self._warehouse = warehouse
        self._reader = reader
        self._renderer = renderer
        self._lockfile = lockfile
        self._site_dir = Path(site_dir)
        self._mode = mode

    def execute(self) -> ReportResult:
        """Release the writer, read the marts and write the site."""
        self._warehouse.close()
        try:
            snapshot = self._reader.read(mode=self._mode)
        finally:
            self._warehouse.open()
        enriched = snapshot.with_sources(
            source_inventory(self._lockfile),
            licenses=self._lockfile.licenses,
            checked_at=self._lockfile.checked_at,
        )
        index = self._renderer.render(enriched, self._site_dir)
        self._write_machine_snapshot(enriched)
        return ReportResult(path=index, batch_count=len(enriched.batches))

    def _write_machine_snapshot(self, snapshot: ReportSnapshot) -> None:
        """Keep a compact machine-readable ledger next to the pages (T10 contract)."""
        self._site_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "mode": snapshot.mode,
            "batches": [dict(row) for row in snapshot.batches],
        }
        (self._site_dir / "report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
