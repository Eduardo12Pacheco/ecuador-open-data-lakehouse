"""Pure half of the D13 decoding policy (UTF-8 first, then cp1252).

Only the byte-to-text rules live here so both the acquisition and the parser
adapters apply exactly the same policy. Filesystem access stays in the
adapters, which keeps the domain free of I/O.
"""

from __future__ import annotations

import codecs

from ecuador_lakehouse.domain.errors import SourceSchemaError

_UTF8_BOM = codecs.BOM_UTF8
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


def _decode_sample(data: bytes, *, final: bool) -> tuple[str, str]:
    decoded = _decode_utf8(data, final=final)
    if decoded is not None:
        return decoded
    cp1252_text = _decode_cp1252(data)
    if cp1252_text is None:
        raise SourceSchemaError(
            "cannot decode source file: neither UTF-8 nor cp1252 accepted the bytes"
        )
    return cp1252_text, "cp1252"


def decode_bytes(data: bytes) -> tuple[str, str]:
    """Decode a complete byte string, returning ``(text, encoding_name)``."""
    return _decode_sample(data, final=True)


def detect_encoding_from_sample(sample: bytes, *, complete: bool) -> str:
    """Return the D13 encoding name for a (possibly partial) byte sample."""
    _text, encoding = _decode_sample(sample, final=complete)
    return encoding
