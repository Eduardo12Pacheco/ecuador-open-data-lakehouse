"""Tests for the pure text parsing helpers shared by EL and dbt."""

from __future__ import annotations

from decimal import Decimal

import pytest

from ecuador_lakehouse.domain.text import (
    ACCENT_MAP,
    normalize_key,
    parse_decimal_comma,
    parse_decimal_dot,
    parse_es_month_abbr,
    parse_es_month_label,
    parse_mixed_decimal,
    parse_thousands_int,
)


def test_normalize_key_removes_accents_and_collapses_punctuation() -> None:
    raw = "CONTRIBUCIÓN PARA LA PROMOCIÓN  DEL TURISMO 1X1000"

    assert normalize_key(raw) == "CONTRIBUCION PARA LA PROMOCION DEL TURISMO 1X1000"


def test_normalize_key_is_case_insensitive_and_trims() -> None:
    assert normalize_key("  impuesto   a la Renta ") == "IMPUESTO A LA RENTA"


def test_normalize_key_handles_every_mapped_accent() -> None:
    accented = "".join(ACCENT_MAP)
    unaccented = "".join(ACCENT_MAP.values())

    assert normalize_key(accented) == normalize_key(unaccented)


def test_normalize_key_replaces_symbols_and_underscores() -> None:
    assert normalize_key("A_B/C--D") == "A B C D"
    assert normalize_key("---") == ""
    assert normalize_key("") == ""


def test_accent_map_covers_the_documented_characters() -> None:
    assert set(ACCENT_MAP) == set("ÁÀÂÄÃÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÑÇ")
    assert ACCENT_MAP["Ñ"] == "N"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("6,084,829", 6084829),
        ("-40,290", -40290),
        ("0", 0),
        (" 123 ", 123),
        ("+1,000", 1000),
        ("1,000,000", 1000000),
    ],
)
def test_parse_thousands_int_accepts_grouped_integers(raw: str, expected: int) -> None:
    assert parse_thousands_int(raw) == expected


@pytest.mark.parametrize("raw", ["", "1,23", "12,34", "1.000", "abc", "1,000.5", "--1"])
def test_parse_thousands_int_rejects_malformed_values(raw: str) -> None:
    with pytest.raises(ValueError, match="thousands"):
        parse_thousands_int(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.224503124", Decimal("0.224503124")),
        ("1.0", Decimal("1.0")),
        ("-3.5", Decimal("-3.5")),
        ("5", Decimal("5")),
        (" 2.25 ", Decimal("2.25")),
    ],
)
def test_parse_decimal_dot(raw: str, expected: Decimal) -> None:
    assert parse_decimal_dot(raw) == expected


@pytest.mark.parametrize("raw", ["", "1,2,3", "1,", "abc", "1 000"])
def test_parse_decimal_dot_rejects_malformed_values(raw: str) -> None:
    with pytest.raises(ValueError, match="decimal"):
        parse_decimal_dot(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("83,3100", Decimal("83.3100")),
        ("1,000000", Decimal("1.000000")),
        ("-0,5", Decimal("-0.5")),
        ("0", Decimal("0")),
    ],
)
def test_parse_decimal_comma(raw: str, expected: Decimal) -> None:
    assert parse_decimal_comma(raw) == expected


@pytest.mark.parametrize("raw", ["", "1.5,2", "1,2,3", "83,", "abc"])
def test_parse_decimal_comma_rejects_malformed_values(raw: str) -> None:
    with pytest.raises(ValueError, match="decimal"):
        parse_decimal_comma(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,000000", Decimal("1.000000")), ("0.224503124", Decimal("0.224503124"))],
)
def test_parse_mixed_decimal_accepts_one_separator_kind(raw: str, expected: Decimal) -> None:
    assert parse_mixed_decimal(raw) == expected


@pytest.mark.parametrize("raw", ["1,234.56", "1.234,56", "", "abc"])
def test_parse_mixed_decimal_rejects_ambiguous_or_empty_values(raw: str) -> None:
    with pytest.raises(ValueError, match="mixed decimal"):
        parse_mixed_decimal(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("01 Enero", 1), ("12 Diciembre", 12), ("Enero", 1), (" 09 septiembre ", 9)],
)
def test_parse_es_month_label(raw: str, expected: int) -> None:
    assert parse_es_month_label(raw) == expected


@pytest.mark.parametrize("raw", ["", "13 Enero", "01 Foo", "02 Enero", "Enero 01"])
def test_parse_es_month_label_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError, match="month"):
        parse_es_month_label(raw)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ene-15", (2015, 1)),
        ("dic-24", (2024, 12)),
        ("ENE-15", (2015, 1)),
        ("sep-2020", (2020, 9)),
    ],
)
def test_parse_es_month_abbr(raw: str, expected: tuple[int, int]) -> None:
    assert parse_es_month_abbr(raw) == expected


@pytest.mark.parametrize("raw", ["", "foo-15", "ene", "ene-1", "ene-15-extra"])
def test_parse_es_month_abbr_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(ValueError, match="month"):
        parse_es_month_abbr(raw)
