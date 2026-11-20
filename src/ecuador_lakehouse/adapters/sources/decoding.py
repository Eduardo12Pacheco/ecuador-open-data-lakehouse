"""Encoding detection and streaming decoding for upstream text files (D13).

The byte-level policy lives in :mod:`ecuador_lakehouse.domain.decoding` so the
parser adapters apply exactly the same rules. This module only adds filesystem
access: detection from a prefix sample and a line iterator for large files.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ecuador_lakehouse.domain.decoding import (
    decode_bytes,
    detect_encoding_from_sample,
)
from ecuador_lakehouse.domain.errors import SourceSchemaError

_DEFAULT_SAMPLE_BYTES = 64 * 1024

__all__ = ["decode_bytes", "detect_encoding", "iter_decoded_lines"]


def detect_encoding(path: Path, *, sample_size: int = _DEFAULT_SAMPLE_BYTES) -> str:
    """Detect the encoding of a file from its first ``sample_size`` bytes."""
    if sample_size <= 0:
        raise ValueError(f"sample_size must be positive: {sample_size!r}")
    with path.open("rb") as handle:
        sample = handle.read(sample_size)
        complete = len(sample) < sample_size
    return detect_encoding_from_sample(sample, complete=complete)


def iter_decoded_lines(path: Path, *, sample_size: int = _DEFAULT_SAMPLE_BYTES) -> Iterator[str]:
    """Yield decoded lines from ``path`` without loading the whole file twice.

    Only the detection sample is read twice; the actual text is produced by a
    streaming decoder, which keeps 100 MB SRI files memory-friendly.
    """
    encoding = detect_encoding(path, sample_size=sample_size)
    try:
        with path.open("r", encoding=encoding, errors="strict", newline="") as handle:
            yield from handle
    except UnicodeDecodeError as exc:
        raise SourceSchemaError(
            f"cannot decode source file {path.name!r} as {encoding}: {exc.reason}"
        ) from exc
