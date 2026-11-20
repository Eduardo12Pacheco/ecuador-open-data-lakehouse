"""Encoding detection and streaming decoding for upstream text files (D13).

The policy is deliberately narrow: try UTF-8 (with an optional BOM) first and
fall back to cp1252 exactly once. ``errors="ignore"`` is forbidden because it
silently corrupts real values; files that decode under neither codec are
rejected with :class:`SourceSchemaError`.
"""

from __future__ import annotations

import codecs
from collections.abc import Iterator
from pathlib import Path

from ecuador_lakehouse.domain.errors import SourceSchemaError

_UTF8_BOM = codecs.BOM_UTF8
_DEFAULT_SAMPLE_BYTES = 64 * 1024
_TAIL_BYTES = 3


def _decode_utf8(data: bytes, *, final: bool) -> tuple[str, str] | None:
    """Return ``(text, encoding_name)`` when ``data`` is valid UTF-8, else ``None``."""
    encoding = "utf-8-sig" if data.startswith(_UTF8_BOM) else "utf-8"
    decoder = codecs.getincrementaldecoder(encoding)("strict")
    try:
        text = decoder.decode(data, final=final)
    except UnicodeDecodeError as exc:
        if not final and exc.start >= len(data) - _TAIL_BYTES:
            # The sample ended in the middle of a multibyte sequence. The file
            # starts as UTF-8; the next chunk continues the same character.
            try:
                return decoder.decode(b"", final=True), encoding
            except UnicodeDecodeError:
                pass
        return None
    return text, encoding


def _decode_cp1252(data: bytes) -> str | None:
    try:
        return data.decode("cp1252", errors="strict")
    except UnicodeDecodeError:
        return None


def _decode_sample(sample: bytes, *, final: bool) -> tuple[str, str]:
    decoded = _decode_utf8(sample, final=final)
    if decoded is not None:
        return decoded
    cp1252_text = _decode_cp1252(sample)
    if cp1252_text is None:
        raise SourceSchemaError(
            "cannot decode source file: neither UTF-8 nor cp1252 accepted the bytes"
        )
    return cp1252_text, "cp1252"


def decode_bytes(data: bytes) -> tuple[str, str]:
    """Decode a complete byte string, returning ``(text, encoding_name)``."""
    return _decode_sample(data, final=True)


def detect_encoding(path: Path, *, sample_size: int = _DEFAULT_SAMPLE_BYTES) -> str:
    """Detect the encoding of a file from its first ``sample_size`` bytes."""
    if sample_size <= 0:
        raise ValueError(f"sample_size must be positive: {sample_size!r}")
    with path.open("rb") as handle:
        sample = handle.read(sample_size)
        complete = len(sample) < sample_size
    _text, encoding = _decode_sample(sample, final=complete)
    return encoding


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
