"""Batch ledger value objects shared by the warehouse and the pipeline."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ecuador_lakehouse.domain.sources import SourceId

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BATCH_ID = re.compile(r"^[0-9a-f]{16}$")


class BatchStatus(StrEnum):
    """Outcome of loading one partition into the raw layer."""

    LOADED = "loaded"
    SKIPPED = "skipped"
    REPLACED = "replaced"


def make_batch_id(source_id: SourceId, partition: str, sha256: str) -> str:
    """Return the deterministic batch id for a source partition vintage."""
    if not partition.strip():
        raise ValueError("partition must not be empty")
    if not _SHA256.fullmatch(sha256):
        raise ValueError(f"sha256 must be 64 lowercase hex characters: {sha256!r}")
    material = f"{source_id}|{partition}|{sha256}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class BatchRecord:
    """A row of ``meta.batches`` describing one load of one partition."""

    batch_id: str
    source_id: SourceId
    partition: str
    source_sha256: str
    row_count: int
    status: BatchStatus
    mode: str
    loaded_at: datetime
    is_current: bool

    def __post_init__(self) -> None:
        if not _BATCH_ID.fullmatch(self.batch_id):
            raise ValueError(f"batch_id must be 16 lowercase hex characters: {self.batch_id!r}")
        if not _SHA256.fullmatch(self.source_sha256):
            raise ValueError(
                f"source_sha256 must be 64 lowercase hex characters: {self.source_sha256!r}"
            )
        if self.row_count < 0:
            raise ValueError(f"row_count must be non-negative: {self.row_count!r}")
        if not self.mode.strip():
            raise ValueError("mode must not be empty")
