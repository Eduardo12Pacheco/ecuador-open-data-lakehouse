"""Property-based tests for text normalization and decimal parsing."""

from __future__ import annotations

import unicodedata
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from ecuador_lakehouse.domain.text import normalize_key, parse_mixed_decimal

ACCENTED_ALPHABET = "ÁÀÂÄÃÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÑÇáéíóúñü"
TEXT_ALPHABET = ACCENTED_ALPHABET + "abcXYZ019 _-./|()%$#\n\t"


@settings(max_examples=100, deadline=None)
@given(st.text(alphabet=TEXT_ALPHABET, max_size=40))
def test_normalize_key_is_idempotent(raw: str) -> None:
    once = normalize_key(raw)

    assert normalize_key(once) == once


@settings(max_examples=100, deadline=None)
@given(st.text(alphabet=TEXT_ALPHABET, max_size=40))
def test_normalize_key_is_accent_insensitive(raw: str) -> None:
    stripped = "".join(
        chr(ord(char)) if char not in ACCENTED_ALPHABET else _strip_accent(char) for char in raw
    )

    assert normalize_key(raw) == normalize_key(stripped)


def _strip_accent(char: str) -> str:
    normalized = unicodedata.normalize("NFKD", char)
    return "".join(part for part in normalized if not unicodedata.combining(part))


@settings(max_examples=100, deadline=None)
@given(
    digits=st.integers(min_value=0, max_value=10**9),
    decimals=st.integers(min_value=0, max_value=6),
    use_comma=st.booleans(),
    negative=st.booleans(),
)
def test_parse_mixed_decimal_round_trips_rendered_decimals(
    digits: int, decimals: int, use_comma: bool, negative: bool
) -> None:
    value = Decimal(digits).scaleb(-decimals)
    if negative:
        value = -value
    rendered = format(value, "f")
    if use_comma:
        rendered = rendered.replace(".", ",")
    expected = Decimal(rendered.replace(",", "."))

    assert parse_mixed_decimal(rendered) == expected
