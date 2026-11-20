"""Build-report use case: write the machine-readable payload for the report UI.

T10 wires the report slot of the pipeline; the full static multi-page site with
vendored ECharts is delivered by T12. This use case currently writes a stable
JSON snapshot (ledger rows and mode) that the page renderer can consume without
touching DuckDB itself, keeping the application layer free of SQL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ecuador_lakehouse.application.ports import Warehouse


@dataclass(frozen=True, slots=True)
class ReportResult:
    """Paths and counts produced by one report run."""

    path: Path
    batch_count: int


class BuildReport:
    """Write ``<site>/report.json`` from the warehouse ledger."""

    def __init__(self, *, warehouse: Warehouse, site_dir: Path, mode: str) -> None:
        self._warehouse = warehouse
        self._site_dir = Path(site_dir)
        self._mode = mode

    def execute(self) -> ReportResult:
        """Open the warehouse, snapshot the current ledger and write JSON."""
        self._warehouse.open()
        batches = [
            {
                "source_id": record.source_id.value,
                "partition": record.partition,
                "sha256": record.source_sha256,
                "rows": record.row_count,
                "status": record.status.value,
                "is_current": record.is_current,
            }
            for record in self._warehouse.ledger()
        ]
        payload = {
            "schema_version": 1,
            "mode": self._mode,
            "batches": batches,
        }
        self._site_dir.mkdir(parents=True, exist_ok=True)
        path = self._site_dir / "report.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return ReportResult(path=path, batch_count=len(batches))
