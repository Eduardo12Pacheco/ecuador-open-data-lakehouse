"""Tests for the INEC CPI wide-format nested-ZIP parser (S5)."""

from __future__ import annotations

import csv
import zipfile
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.parsers.inec_cpi import InecCpiParser
from ecuador_lakehouse.application.ports import SourceParser
from ecuador_lakehouse.domain.errors import SourceSchemaError
from ecuador_lakehouse.domain.sources import SourceId

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "parsers"
CANONICAL_HEADER = [
    "price_area",
    "nivel",
    "ponderacion_raw",
    "codigo_ccif",
    "descripcion",
    "month_label",
    "value_raw",
]


def _read_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def test_parser_implements_the_source_parser_port() -> None:
    parser = InecCpiParser()

    assert isinstance(parser, SourceParser)
    assert parser.source_id is SourceId.INEC_CPI


def test_walks_nested_zips_and_melts_months_to_long_rows(tmp_path: Path) -> None:
    result = InecCpiParser().parse(FIXTURES / "inec_mini.zip", "2024-12", output_dir=tmp_path)

    rows = _read_rows(result.path)

    assert result.row_count == 13
    assert result.partition == "2024-12"
    assert rows[0] == CANONICAL_HEADER
    assert {row[0] for row in rows[1:]} == {"NACIONAL", "REGION SIERRA"}
    assert {row[5] for row in rows[1:]} == {"ene-15", "feb-15", "dic-24"}


def test_weights_keep_the_mixed_decimal_text_verbatim(tmp_path: Path) -> None:
    result = InecCpiParser().parse(FIXTURES / "inec_mini.zip", "2024-12", output_dir=tmp_path)

    rows = _read_rows(result.path)
    weights = {(row[0], row[1], row[3], row[2]) for row in rows[1:]}

    assert ("NACIONAL", "General", "0", "1,000000") in weights
    assert ("NACIONAL", "División", "1", "0.224503124") in weights


def test_values_keep_comma_and_dot_decimals_and_drop_empty_cells(tmp_path: Path) -> None:
    result = InecCpiParser().parse(FIXTURES / "inec_mini.zip", "2024-12", output_dir=tmp_path)

    rows = _read_rows(result.path)
    nacional = [row for row in rows[1:] if row[0] == "NACIONAL" and row[3] == "1"]

    assert ("ene-15", "95,10") in {(row[5], row[6]) for row in nacional}
    assert "feb-15" not in {row[5] for row in nacional}
    assert {row[6] for row in rows[1:]} & {"101.45", "100.00"}


def test_footer_rows_are_excluded(tmp_path: Path) -> None:
    result = InecCpiParser().parse(FIXTURES / "inec_mini.zip", "2024-12", output_dir=tmp_path)

    rows = _read_rows(result.path)

    assert all(row[1] not in {"", "Nota: Información provisional"} for row in rows[1:])
    assert all("Nota" not in row[4] for row in rows[1:])


def test_flat_sample_zip_is_supported(tmp_path: Path) -> None:
    flat = tmp_path / "inec_cpi_index_2024-12.zip"
    csv_text = (
        "Título\r\nBase 2014=100\r\nActualizado\r\nFuente\r\n"
        "Nivel,Ponderación,Cód. CCIF,Descripción CCIF,ene-15,dic-24\r\n"
        'General,"1,000000",0,Índice general,"101,24",\r\n'
        "Nota: sin datos\r\n"
    )
    with zipfile.ZipFile(flat, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("1. NACIONAL.csv", csv_text.encode("cp1252"))

    result = InecCpiParser().parse(flat, "2024-12", output_dir=tmp_path / "out")

    rows = _read_rows(result.path)
    assert result.row_count == 1
    assert rows[1] == ["NACIONAL", "General", "1,000000", "0", "Índice general", "ene-15", "101,24"]


def test_missing_header_row_is_a_schema_error(tmp_path: Path) -> None:
    broken = tmp_path / "inec_broken.zip"
    with zipfile.ZipFile(broken, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("1. NACIONAL.csv", "sin encabezado\r\n1,2,3\r\n".encode("cp1252"))

    with pytest.raises(SourceSchemaError, match="Nivel"):
        InecCpiParser().parse(broken, "2024-12", output_dir=tmp_path)


def test_malformed_zip_is_a_schema_error(tmp_path: Path) -> None:
    broken = tmp_path / "not_a_zip.zip"
    broken.write_bytes(b"not a zip file")

    with pytest.raises(SourceSchemaError, match="ZIP"):
        InecCpiParser().parse(broken, "2024-12", output_dir=tmp_path)


def test_trailing_empty_padding_cells_are_tolerated(tmp_path: Path) -> None:
    padded = tmp_path / "inec_padded.zip"
    padding = "," * 60
    csv_text = (
        f"Título{padding}\r\nBase 2014=100{padding}\r\nActualizado{padding}\r\nFuente{padding}\r\n"
        f"Nivel,Ponderación,Cód. CCIF,Descripción CCIF,ene-15{padding}\r\n"
        f'General,"1,000000",0,Índice general,"101,24"{padding}\r\n'
    )
    with zipfile.ZipFile(padded, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ipc_ind_nac_reg_ciud_12_2024/1. NACIONAL.csv", csv_text.encode("cp1252"))

    result = InecCpiParser().parse(padded, "2024-12", output_dir=tmp_path / "out")

    rows = _read_rows(result.path)
    assert result.row_count == 1
    assert rows[1] == ["NACIONAL", "General", "1,000000", "0", "Índice general", "ene-15", "101,24"]


def test_numbered_files_outside_the_cpi_series_are_ignored(tmp_path: Path) -> None:
    archive_path = tmp_path / "inec_extra.zip"
    cpi_csv = (
        "Título\r\nBase 2014=100\r\nActualizado\r\nFuente\r\n"
        "Nivel,Ponderación,Cód. CCIF,Descripción CCIF,ene-15\r\n"
        'General,"1,000000",0,Índice general,"101,24"\r\n'
    )
    other_csv = "Concepto,ene-15\r\nÍndice de variación,10,00\r\n"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ipc_ind_nac_reg_ciud_12_2024/1. NACIONAL.csv", cpi_csv.encode("cp1252"))
        archive.writestr(
            "ipc_var_anu_nac_reg_ciud_12_2024/1. NACIONAL.csv", other_csv.encode("cp1252")
        )

    result = InecCpiParser().parse(archive_path, "2024-12", output_dir=tmp_path / "out")

    assert result.row_count == 1
