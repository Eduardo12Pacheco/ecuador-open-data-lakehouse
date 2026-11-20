"""Tests for the D13 decoding policy (UTF-8 first, then cp1252)."""

from __future__ import annotations

import codecs
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.sources.decoding import (
    decode_bytes,
    detect_encoding,
    iter_decoded_lines,
)
from ecuador_lakehouse.domain.errors import SourceSchemaError

ACCENTED = "Recaudación de impuestos; contribuyente; Guayaquil\n"


def test_utf8_without_bom_is_decoded_as_utf8() -> None:
    text, encoding = decode_bytes(ACCENTED.encode("utf-8"))

    assert text == ACCENTED
    assert encoding == "utf-8"


def test_utf8_bom_is_stripped_and_reported() -> None:
    text, encoding = decode_bytes(codecs.BOM_UTF8 + ACCENTED.encode("utf-8"))

    assert text == ACCENTED
    assert not text.startswith("\ufeff")
    assert encoding == "utf-8-sig"


def test_cp1252_is_the_fallback_for_non_utf8_files() -> None:
    text, encoding = decode_bytes(ACCENTED.encode("cp1252"))

    assert text == ACCENTED
    assert encoding == "cp1252"


def test_bytes_invalid_in_both_codecs_raise_a_source_schema_error() -> None:
    with pytest.raises(SourceSchemaError, match="decode"):
        decode_bytes(b"valid text\x81invalid")


def test_empty_input_decodes_as_empty_utf8() -> None:
    assert decode_bytes(b"") == ("", "utf-8")


def test_detect_encoding_reads_only_a_sample(tmp_path: Path) -> None:
    path = tmp_path / "sri.csv"
    path.write_bytes(codecs.BOM_UTF8 + (ACCENTED * 5000).encode("utf-8"))

    assert detect_encoding(path, sample_size=128) == "utf-8-sig"


def test_detect_encoding_tolerates_a_multibyte_character_cut_by_the_sample(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cut.csv"
    prefix = b"a" * 63
    path.write_bytes(prefix + "ó".encode() + b"\n")

    assert detect_encoding(path, sample_size=64) == "utf-8"


def test_iter_decoded_lines_streams_utf8_and_strips_the_bom(tmp_path: Path) -> None:
    path = tmp_path / "sri.csv"
    path.write_bytes(codecs.BOM_UTF8 + "AÑO|MES\n2024|01 Enero\n".encode())

    assert list(iter_decoded_lines(path)) == ["AÑO|MES\n", "2024|01 Enero\n"]


def test_iter_decoded_lines_streams_cp1252(tmp_path: Path) -> None:
    path = tmp_path / "sri_2024.csv"
    path.write_bytes("AÑO|MES\n2024|01 Enero\n".encode("cp1252"))

    assert list(iter_decoded_lines(path)) == ["AÑO|MES\n", "2024|01 Enero\n"]


def test_iter_decoded_lines_rejects_undecodable_bytes(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_bytes(b"header\nvalue\x81\n")

    with pytest.raises(SourceSchemaError, match="decode"):
        list(iter_decoded_lines(path))


def test_iter_decoded_lines_rejects_a_late_undecodable_byte(tmp_path: Path) -> None:
    path = tmp_path / "late.csv"
    path.write_bytes(b"a" * 200 + b"\x81")

    with pytest.raises(SourceSchemaError, match="decode"):
        list(iter_decoded_lines(path, sample_size=16))


def test_iter_decoded_lines_handles_an_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")

    assert list(iter_decoded_lines(path)) == []
