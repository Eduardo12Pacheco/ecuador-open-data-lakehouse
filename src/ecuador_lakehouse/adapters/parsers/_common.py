"""Shared helpers for the structural parser adapters (D4, D5).

Parsers only extract structure: decode, detect the header, map columns and
write canonical UTF-8 CSV. Typing, cleaning and modelling belong to dbt.
"""

from __future__ import annotations

import csv
import gzip
import io
import re
import tempfile
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path, PurePosixPath
from typing import TextIO

from ecuador_lakehouse.domain.decoding import detect_encoding_from_sample
from ecuador_lakehouse.domain.errors import SourceSchemaError
from ecuador_lakehouse.domain.sources import SourceId

_SAMPLE_BYTES = 64 * 1024
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_COMPRESSION_RATIO = 200.0


def _open_binary(path: Path) -> io.BufferedReader | gzip.GzipFile:
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rb")
    return path.open("rb")


def open_source_text(path: Path) -> TextIO:
    """Open a plain or gzip-compressed source file with the D13 encoding policy."""
    with _open_binary(path) as raw:
        sample = raw.read(_SAMPLE_BYTES)
        complete = len(sample) < _SAMPLE_BYTES
    encoding = detect_encoding_from_sample(sample, complete=complete)
    raw = _open_binary(path)
    return io.TextIOWrapper(raw, encoding=encoding, errors="strict", newline="")


def canonical_output_path(output_dir: Path | None, source_id: SourceId, partition: str) -> Path:
    """Return the canonical CSV path, creating a temporary directory when needed."""
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix=f"lakehouse-{source_id.value}-"))
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
    safe_partition = _UNSAFE_FILENAME.sub("-", partition).strip("-") or "partition"
    return output_dir / f"{source_id.value}_{safe_partition}.csv"


def trim_trailing_empty(row: Sequence[str]) -> list[str]:
    """Drop purely empty trailing cells added by upstream CSV padding."""
    cells = list(row)
    while cells and not cells[-1].strip():
        cells.pop()
    return cells


def first_non_empty_row(reader: Iterator[Sequence[str]], *, label: str) -> list[str]:
    """Return the first row with at least one non-blank cell (the header row)."""
    for row in reader:
        if any(cell.strip() for cell in row):
            return list(row)
    raise SourceSchemaError(f"{label} is empty: no header row found")


def require_columns(
    header: Sequence[str],
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
    ignored: Sequence[str] = (),
    label: str,
) -> dict[str, int]:
    """Validate an upstream header and return the position of every column."""
    names = [name.strip() for name in header]
    positions: dict[str, int] = {}
    for index, name in enumerate(names):
        if not name:
            raise SourceSchemaError(
                f"{label} header has an empty column name at position {index + 1}"
            )
        if name in positions:
            raise SourceSchemaError(f"{label} header has a duplicate column: {name!r}")
        positions[name] = index
    allowed = set(required) | set(optional) | set(ignored)
    missing = [name for name in required if name not in positions]
    if missing:
        raise SourceSchemaError(
            f"{label} header is missing required column(s): {', '.join(missing)}"
        )
    unknown = [name for name in names if name not in allowed]
    if unknown:
        raise SourceSchemaError(f"{label} header has unknown column(s): {', '.join(unknown)}")
    return positions


def pad_row(row: Sequence[str], width: int, *, line_number: int, label: str) -> list[str]:
    """Pad missing trailing fields with empty strings; reject extra fields."""
    cells = trim_trailing_empty(row)
    if len(cells) > width:
        raise SourceSchemaError(
            f"{label} line {line_number} has {len(cells)} fields but the header has {width}"
        )
    return [*cells, *([""] * (width - len(cells)))]


def write_canonical_csv(
    path: Path, *, columns: Sequence[str], rows: Iterable[Sequence[str]]
) -> int:
    """Write canonical UTF-8 CSV (LF line endings) and return the data row count."""
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def read_zip_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    max_bytes: int = 300 * 1024 * 1024,
) -> bytes:
    """Read one ZIP member in memory after the parser-side safety checks.

    Nested CPI archives are never extracted to disk, so only the guards that
    still matter apply: safe member names, a per-member size cap, a
    decompression-ratio cap and a declared/streamed size agreement.
    """
    name = info.filename
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or PurePosixPath(name).is_absolute()
        or ".." in PurePosixPath(name).parts
    ):
        raise SourceSchemaError(f"unsafe archive member name: {name!r}")
    if info.file_size > max_bytes:
        raise SourceSchemaError(
            f"archive member {name!r} expands to {info.file_size} bytes, above the cap"
        )
    if (
        info.file_size > 0
        and info.compress_size > 0
        and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO
    ):
        raise SourceSchemaError(f"archive member {name!r} has a suspicious compression ratio")
    with archive.open(info) as source:
        data = source.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise SourceSchemaError(f"archive member {name!r} streamed above the size cap")
    if len(data) != info.file_size:
        raise SourceSchemaError(f"archive member {name!r} does not match its declared size")
    return data
