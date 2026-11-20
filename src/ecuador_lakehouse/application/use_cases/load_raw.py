"""Load-raw use case: canonicalize acquired files and load them one by one (S6).

The use case is deliberately thin: it owns the Strategy lookup (one parser per
source) and the temporary directory where canonical CSVs are written; the
warehouse adapter owns the transaction and the ledger. Acquired files stay in
the fetcher cache, so a later step can reuse them.
"""

from __future__ import annotations

import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ecuador_lakehouse.application.ports import FetchResult, LoadResult, SourceParser, Warehouse
from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sources import SourceId


@dataclass(frozen=True, slots=True)
class LoadRaw:
    """Turn freshly acquired files into raw rows through the parser and warehouse."""

    parsers: Mapping[SourceId, SourceParser]
    warehouse: Warehouse

    def execute(
        self,
        fetched: Sequence[FetchResult],
        *,
        output_dir: Path | None = None,
    ) -> list[LoadResult]:
        """Load every acquired partition in the given order and report each outcome."""
        if not fetched:
            return []
        if output_dir is not None:
            return self._load(fetched, output_dir)
        with tempfile.TemporaryDirectory(prefix="lakehouse-load-") as tmp:
            return self._load(fetched, Path(tmp))

    def _load(self, fetched: Sequence[FetchResult], output_dir: Path) -> list[LoadResult]:
        results: list[LoadResult] = []
        for acquired in fetched:
            source_file = acquired.source_file
            parser = self.parsers.get(source_file.source_id)
            if parser is None:
                raise ConfigError(
                    f"no parser registered for source {source_file.source_id.value!r}"
                )
            parsed = parser.parse(acquired.path, source_file.partition, output_dir=output_dir)
            try:
                results.append(
                    self.warehouse.load_partition(
                        source_file.source_id,
                        source_file.partition,
                        parsed.path,
                        acquired.sha256,
                        acquired.path.name,
                    )
                )
            finally:
                parsed.path.unlink(missing_ok=True)
        return results
