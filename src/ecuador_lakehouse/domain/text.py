"""Pure text normalization and parsing primitives shared by Python and dbt.

The helpers here are the Python side of decision D12/D13/D28: normalization
must be byte-for-byte reproducible in SQL (``macros/norm_key.sql``) and month
parsing must never depend on the process locale.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_ACCENTED = "ÁÀÂÄÃÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÑÇ"
_UNACCENTED = "AAAAAEEEEIIIIOOOOOUUUUNC"

#: Accented characters mapped to their unaccented uppercase counterpart (D12).
#: Keys are uppercase on purpose: :func:`normalize_key` uppercases first.
ACCENT_MAP: dict[str, str] = dict(zip(_ACCENTED, _UNACCENTED, strict=True))
_ACCENT_TRANSLATION = str.maketrans(_ACCENTED, _UNACCENTED)

_MONTHS_ES: dict[str, int] = {
    "ENERO": 1,
    "FEBRERO": 2,
    "MARZO": 3,
    "ABRIL": 4,
    "MAYO": 5,
    "JUNIO": 6,
    "JULIO": 7,
    "AGOSTO": 8,
    "SEPTIEMBRE": 9,
    "OCTUBRE": 10,
    "NOVIEMBRE": 11,
    "DICIEMBRE": 12,
}

_MONTHS_ABBR: dict[str, int] = {
    "ENE": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12,
}

_NON_KEY_CHARS = re.compile(r"[^A-Z0-9]+")
_THOUSANDS = re.compile(r"^[+-]?\d{1,3}(?:,\d{3})+$|^[+-]?\d+$")
_DECIMAL_DOT = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_DECIMAL_COMMA = re.compile(r"^[+-]?\d+(?:,\d+)?$")
_MONTH_LABEL = re.compile(r"^(?:(\d{1,2})\s+)?([A-Za-z]+)$")
_MONTH_ABBR = re.compile(r"^([A-Za-z]{3})-(\d{2}|\d{4})$")
_SHORT_YEAR_LENGTH = 2


def normalize_key(value: str) -> str:
    """Return the canonical comparison key for a human label.

    Uppercases, strips accents through :data:`ACCENT_MAP`, replaces every run
    of characters outside ``[A-Z0-9]`` with a single space and trims. The
    result is idempotent and accent-insensitive.
    """
    translated = value.upper().translate(_ACCENT_TRANSLATION)
    return _NON_KEY_CHARS.sub(" ", translated).strip()


def parse_thousands_int(value: str) -> int:
    """Parse an integer that may use comma thousands separators.

    Examples: ``"6,084,829"`` -> ``6084829``, ``"-40,290"`` -> ``-40290``.
    """
    text = value.strip()
    if not text or not _THOUSANDS.match(text):
        raise ValueError(f"invalid thousands integer: {value!r}")
    try:
        return int(text.replace(",", ""))
    except ValueError as exc:  # pragma: no cover - guarded by the regex above
        raise ValueError(f"invalid thousands integer: {value!r}") from exc


def parse_decimal_dot(value: str) -> Decimal:
    """Parse a decimal number that uses a dot as its only separator."""
    text = value.strip()
    if not text or not _DECIMAL_DOT.match(text):
        raise ValueError(f"invalid decimal value: {value!r}")
    try:
        return Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex above
        raise ValueError(f"invalid decimal value: {value!r}") from exc


def parse_decimal_comma(value: str) -> Decimal:
    """Parse a decimal number that uses a comma as its only separator."""
    text = value.strip()
    if not text or not _DECIMAL_COMMA.match(text):
        raise ValueError(f"invalid decimal value: {value!r}")
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex above
        raise ValueError(f"invalid decimal value: {value!r}") from exc


def parse_mixed_decimal(value: str) -> Decimal:
    """Parse a decimal that may use either a comma or a dot, never both.

    INEC CPI files mix ``1,000000`` and ``0.224503124`` in the same column.
    A value containing both separators is ambiguous, hence rejected.
    """
    text = value.strip()
    if not text:
        raise ValueError(f"invalid mixed decimal value: {value!r}")
    has_comma = "," in text
    has_dot = "." in text
    if has_comma and has_dot:
        raise ValueError(f"invalid mixed decimal value: {value!r} contains both separators")
    try:
        if has_comma:
            return parse_decimal_comma(text)
        return parse_decimal_dot(text)
    except ValueError as exc:
        raise ValueError(f"invalid mixed decimal value: {value!r}") from exc


def parse_es_month_label(value: str) -> int:
    """Parse a Spanish month label such as ``"01 Enero"`` into ``1``."""
    text = " ".join(value.split())
    match = _MONTH_LABEL.match(text)
    if match is None:
        raise ValueError(f"invalid month label: {value!r}")
    number_text, name_text = match.groups()
    number = _MONTHS_ES.get(name_text.upper())
    if number is None:
        raise ValueError(f"invalid month label: {value!r}")
    if number_text is not None:
        prefix = int(number_text)
        if prefix != number:
            raise ValueError(f"invalid month label: {value!r}")
    return number


def parse_es_month_abbr(value: str) -> tuple[int, int]:
    """Parse a Spanish month abbreviation such as ``"ene-15"`` to ``(2015, 1)``."""
    text = value.strip()
    match = _MONTH_ABBR.match(text)
    if match is None:
        raise ValueError(f"invalid month abbreviation: {value!r}")
    month_text, year_text = match.groups()
    month = _MONTHS_ABBR.get(month_text.upper())
    if month is None:
        raise ValueError(f"invalid month abbreviation: {value!r}")
    year = int(year_text)
    if len(year_text) == _SHORT_YEAR_LENGTH:
        year += 2000
    return year, month
