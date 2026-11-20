"""Safe ZIP inspection and extraction for untrusted upstream archives (S21).

Three independent guards protect the filesystem: member names must stay inside
the destination, absolute/backslash/symlink entries are rejected, and the
declared and streamed uncompressed sizes are capped per member, in total and
against the compressed size (decompression-bomb ratio).
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ecuador_lakehouse.domain.errors import UnsafeArchiveError

_MIB = 1024 * 1024
_S_IFMT = 0o170000
_S_IFLNK = 0o120000


@dataclass(frozen=True, slots=True)
class ZipLimits:
    """Hard limits applied to every extracted archive."""

    max_member_bytes: int = 300 * _MIB
    max_total_bytes: int = 600 * _MIB
    max_compression_ratio: float = 200.0

    def __post_init__(self) -> None:
        if self.max_member_bytes <= 0:
            raise ValueError("max_member_bytes must be positive")
        if self.max_total_bytes <= 0:
            raise ValueError("max_total_bytes must be positive")
        if self.max_compression_ratio <= 1:
            raise ValueError("max_compression_ratio must be greater than 1")


DEFAULT_LIMITS = ZipLimits()
_READ_CHUNK = 1024 * 1024


def _member_label(info: zipfile.ZipInfo) -> str:
    return info.filename


def _unsafe(info: zipfile.ZipInfo, reason: str) -> UnsafeArchiveError:
    return UnsafeArchiveError(f"unsafe archive member {_member_label(info)!r}: {reason}")


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & _S_IFMT == _S_IFLNK


def _validate_name(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if not name:
        raise _unsafe(info, "empty name")
    if "\x00" in name:
        raise _unsafe(info, "NUL byte in name")
    if "\\" in name:
        raise _unsafe(info, "backslash separator")
    if name.startswith("/") or PurePosixPath(name).is_absolute():
        raise _unsafe(info, "absolute path")
    parts = PurePosixPath(name).parts
    if ".." in parts:
        raise _unsafe(info, "parent directory traversal")
    if any(part in ("", ".") for part in parts):
        raise _unsafe(info, "ambiguous path segment")


def _validate_size(info: zipfile.ZipInfo, limits: ZipLimits) -> None:
    if info.is_dir():
        return
    if _is_symlink(info):
        raise _unsafe(info, "symlink members are not allowed")
    if info.file_size > limits.max_member_bytes:
        raise _unsafe(
            info,
            f"per-member size {info.file_size} exceeds {limits.max_member_bytes} bytes",
        )
    if info.file_size > 0:
        if info.compress_size <= 0:
            raise _unsafe(info, "compressed size is zero for a non-empty member")
        ratio = info.file_size / info.compress_size
        if ratio > limits.max_compression_ratio:
            raise _unsafe(
                info,
                f"compression ratio {ratio:.0f}x exceeds {limits.max_compression_ratio:.0f}x",
            )


def validate_member(info: zipfile.ZipInfo, limits: ZipLimits = DEFAULT_LIMITS) -> None:
    """Validate one archive member before any of its bytes are written."""
    _validate_name(info)
    _validate_size(info, limits)


def _checked_target(destination: Path, info: zipfile.ZipInfo) -> Path:
    target = destination.joinpath(*PurePosixPath(info.filename).parts)
    try:
        target.resolve().relative_to(destination.resolve())
    except ValueError as exc:
        raise _unsafe(info, "resolves outside the destination") from exc
    return target


def _check_total(total: int, limits: ZipLimits) -> None:
    if total > limits.max_total_bytes:
        raise UnsafeArchiveError(
            f"unsafe archive: total uncompressed size exceeds {limits.max_total_bytes} bytes"
        )


def safe_extract(
    archive: zipfile.ZipFile,
    destination: Path,
    limits: ZipLimits = DEFAULT_LIMITS,
) -> list[Path]:
    """Extract a ZIP archive into ``destination`` after validating every member."""
    destination.mkdir(parents=True, exist_ok=True)
    members = archive.infolist()
    total = 0
    for info in members:
        validate_member(info, limits)
        if not info.is_dir():
            total += info.file_size
    _check_total(total, limits)

    written: list[Path] = []
    for info in members:
        if info.is_dir():
            destination.joinpath(*PurePosixPath(info.filename).parts).mkdir(
                parents=True, exist_ok=True
            )
            continue
        target = _checked_target(destination, info)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, target.open("wb") as sink:
            streamed = 0
            while chunk := source.read(_READ_CHUNK):
                streamed += len(chunk)
                if streamed > limits.max_member_bytes:
                    raise _unsafe(info, "streamed size exceeds the per-member cap")
                sink.write(chunk)
            if streamed != info.file_size:
                raise _unsafe(info, "streamed size does not match the declared size")
        written.append(target)
    return written


def safe_extract_path(
    archive_path: Path,
    destination: Path,
    limits: ZipLimits = DEFAULT_LIMITS,
) -> list[Path]:
    """Open ``archive_path`` and extract it with :func:`safe_extract`."""
    try:
        with zipfile.ZipFile(archive_path) as archive:
            return safe_extract(archive, destination, limits)
    except zipfile.BadZipFile as exc:
        raise UnsafeArchiveError(f"unsafe archive {archive_path.name!r}: not a ZIP file") from exc


def safe_read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    limits: ZipLimits = DEFAULT_LIMITS,
) -> bytes:
    """Read one member into memory while enforcing the same limits as extraction."""
    validate_member(info, limits)
    with archive.open(info) as source:
        data = source.read(limits.max_member_bytes + 1)
    if len(data) > limits.max_member_bytes:
        raise _unsafe(info, "streamed size exceeds the per-member cap")
    if len(data) != info.file_size:
        raise _unsafe(info, "streamed size does not match the declared size")
    return data
