"""Tests for the SRI tax-collection parser (S5, D13)."""

from __future__ import annotations

import csv
import gzip
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.parsers.sri_tax import SriTaxParser
from ecuador_lakehouse.application.ports import SourceParser
from ecuador_lakehouse.domain.errors import SourceSchemaError
from ecuador_lakehouse.domain.sources import SourceId

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "parsers"
CANONICAL_HEADER = [
    "anio",
    "mes_label",
    "grupo",
    "subgrupo",
    "impuesto",
    "tipo_contribuyente",
    "provincia",
    "canton",
    "valor_raw",
]


def _read_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_parser_implements_the_source_parser_port() -> None:
    parser = SriTaxParser()

    assert isinstance(parser, SourceParser)
    assert parser.source_id is SourceId.SRI_TAX


def test_utf8_bom_and_cp1252_yield_identical_canonical_rows(tmp_path: Path) -> None:
    parser = SriTaxParser()

    utf8_result = parser.parse(FIXTURES / "sri_utf8_bom.csv", "2024", output_dir=tmp_path / "a")
    cp1252_result = parser.parse(FIXTURES / "sri_cp1252.csv", "2024", output_dir=tmp_path / "b")

    assert utf8_result.row_count == cp1252_result.row_count == 4
    assert _read_rows(utf8_result.path) == _read_rows(cp1252_result.path)


def test_canonical_rows_preserve_accents_and_comma_decimals(tmp_path: Path) -> None:
    result = SriTaxParser().parse(FIXTURES / "sri_cp1252.csv", "2024", output_dir=tmp_path)

    rows = _read_rows(result.path)

    assert rows[0] == CANONICAL_HEADER
    assert rows[1] == [
        "2024",
        "01 Enero",
        "IMPUESTO AL VALOR AGREGADO",
        "IVA",
        "IVA 15%",
        "SOCIEDADES",
        "GUAYAS",
        "GUAYAQUIL",
        "83,3100",
    ]
    assert rows[4][2] == "ÓRGANO DE CONTROL"
    assert rows[4][4] == "CONTRIBUCIÓN ¿SEGURIDAD?"
    assert rows[4][8] == "-12,50"


def test_optional_canton_is_empty_for_the_eight_column_sample(tmp_path: Path) -> None:
    result = SriTaxParser().parse(FIXTURES / "sri_sample_8col.csv", "2025", output_dir=tmp_path)

    rows = _read_rows(result.path)

    assert result.row_count == 2
    assert rows[1][7] == ""
    assert rows[2][7] == ""


def test_missing_required_column_names_the_column(tmp_path: Path) -> None:
    with pytest.raises(SourceSchemaError, match="PROVINCIA"):
        SriTaxParser().parse(FIXTURES / "sri_missing_column.csv", "2024", output_dir=tmp_path)


def test_unknown_column_names_the_column(tmp_path: Path) -> None:
    source = tmp_path / "sri_unknown.csv"
    source.write_text(
        "ANIO|MES|GRUPO_IMPUESTO|SUBGRUPO_IMPUESTO|IMPUESTO|TIPO_CONTRIBUYENTE"
        "|PROVINCIA|VALOR_RECAUDADO|EXTRA\n2024|01 Enero|G|S|I|SOCIEDADES|GUAYAS|1,00|x\n",
        encoding="utf-8",
    )

    with pytest.raises(SourceSchemaError, match="EXTRA"):
        SriTaxParser().parse(source, "2024", output_dir=tmp_path)


def test_canonical_output_is_utf8_without_bom(tmp_path: Path) -> None:
    result = SriTaxParser().parse(FIXTURES / "sri_utf8_bom.csv", "2024", output_dir=tmp_path)

    assert result.path.read_bytes()[:3] != b"\xef\xbb\xbf"
    assert "ÓRGANO" in result.path.read_text(encoding="utf-8")


def test_gzipped_source_files_are_transparently_decompressed(tmp_path: Path) -> None:
    compressed = tmp_path / "sri_2024.csv.gz"
    with gzip.open(compressed, "wb") as handle:
        handle.write((FIXTURES / "sri_utf8_bom.csv").read_bytes())

    result = SriTaxParser().parse(compressed, "2024", output_dir=tmp_path / "out")

    assert result.row_count == 4
    assert result.path.name == "sri_tax_2024.csv"
