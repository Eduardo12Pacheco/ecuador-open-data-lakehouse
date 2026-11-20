"""Persistent ledger of accepted checksums for mutable upstream files (S4).

The current-year SRI file is refreshed upstream every month. Its pinned
checksum is expected to drift, so a new checksum is accepted only when the
operator passes ``--accept-new-vintage``; the accepted value is remembered
under the local cache directory, never written back into the package.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sources import SourceFile


class VintageLedger:
    """Read and write the ``vintages.json`` ledger for one cache root."""

    def __init__(self, cache_root: Path) -> None:
        self._cache_root = cache_root

    def accepted_sha(self, source_file: SourceFile) -> str | None:
        """Return the checksum accepted for this partition, if one was recorded."""
        entry = self._read(source_file).get(source_file.partition)
        if not isinstance(entry, dict):
            return None
        sha = entry.get("sha256")
        return sha if isinstance(sha, str) else None

    def record(self, source_file: SourceFile, sha256: str, size_bytes: int) -> None:
        """Persist an accepted checksum for a mutable partition."""
        path = self._path(source_file)
        payload = self._read(source_file)
        payload[source_file.partition] = {
            "sha256": sha256,
            "size_bytes": size_bytes,
            "pinned_sha256": source_file.sha256,
            "accepted": True,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _path(self, source_file: SourceFile) -> Path:
        return self._cache_root / source_file.source_id.value / "vintages.json"

    def _read(self, source_file: SourceFile) -> dict[str, Any]:
        path = self._path(source_file)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"invalid vintage ledger {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ConfigError(f"invalid vintage ledger {path}: expected a JSON object")
        return payload
