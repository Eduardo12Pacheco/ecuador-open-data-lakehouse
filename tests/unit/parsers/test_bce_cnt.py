"""Tests for the BCE national-accounts parser (S5)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.parsers.bce_cnt import BceCntParser
from ecuador_lakehouse.application.ports import SourceParser
from ecuador_lakehouse.domain.errors import SourceSchemaError
from ecuador_lakehouse.domain.sources import SourceId

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "parsers"
CANONICAL_HEADER = [
    "tipo_variable",
    "variable",
    "codigo",
    "descripcion",
    "unidades",
    "anio",
    "trimestre",
    "valor_raw",
]


def _read_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_parser_implements_the_source_parser_port() -> None:
    parser = BceCntParser()

    assert isinstance(parser, SourceParser)
    assert parser.source_id is SourceId.BCE_CNT


def test_parses_cp1252_semicolon_delimited_rows_as_raw_text(tmp_path: Path) -> None:
    result = BceCntParser().parse(FIXTURES / "bce_mini.csv", "2000Q1-2021Q1", output_dir=tmp_path)

    rows = _read_rows(result.path)

    assert result.row_count == 4
    assert rows[0] == CANONICAL_HEADER
    assert rows[1] == [
        "Valor",
        "Manufactura",
        "I003",
        "Manufactura",
        "Miles de dólares",
        "2000",
        "I",
        "6,084,829",
    ]
    assert rows[1][4] == "Miles de dólares"


def test_empty_values_stay_empty_and_negative_thousands_are_raw(tmp_path: Path) -> None:
    result = BceCntParser().parse(FIXTURES / "bce_mini.csv", "2000Q1-2021Q1", output_dir=tmp_path)

    rows = _read_rows(result.path)

    assert rows[2][7] == "-40,290"
    assert rows[3][7] == ""
    assert rows[4][5] == "2001"


def test_missing_required_column_names_the_column(tmp_path: Path) -> None:
    source = tmp_path / "bce_missing.csv"
    source.write_bytes(
        (
            "Tipo Variable;Variable;Código Industria-Producto;Industrias-Productos;"
            "Unidades;Año;Trimestre\nValor;Manufactura;I003;Manufactura;USD;2000;I\n"
        ).encode("cp1252")
    )

    with pytest.raises(SourceSchemaError, match="Valor"):
        BceCntParser().parse(source, "2000Q1-2021Q1", output_dir=tmp_path)


def test_unknown_column_names_the_column(tmp_path: Path) -> None:
    source = tmp_path / "bce_unknown.csv"
    source.write_bytes(
        (
            "Tipo Variable;Variable;Código Industria-Producto;Industrias-Productos;"
            "Unidades;Año;Trimestre;Valor;Extra\n"
            "Valor;Manufactura;I003;Manufactura;USD;2000;I;1,000;x\n"
        ).encode("cp1252")
    )

    with pytest.raises(SourceSchemaError, match="Extra"):
        BceCntParser().parse(source, "2000Q1-2021Q1", output_dir=tmp_path)
