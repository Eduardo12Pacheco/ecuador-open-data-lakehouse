"""Property test: SRI parsing is independent of the source encoding (S5, D13)."""

from __future__ import annotations

import csv
import string
import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from ecuador_lakehouse.adapters.parsers.sri_tax import SriTaxParser

HEADER = (
    "ANIO",
    "MES",
    "GRUPO_IMPUESTO",
    "SUBGRUPO_IMPUESTO",
    "IMPUESTO",
    "TIPO_CONTRIBUYENTE",
    "PROVINCIA",
    "VALOR_RECAUDADO",
)
ALPHABET = string.ascii_letters + string.digits + " ÁÉÍÓÚÑáéíóúñ¿.,-_/()"
cell = st.text(alphabet=ALPHABET, max_size=24)
row = st.tuples(*(cell for _ in HEADER))
rows = st.lists(row, max_size=12)


def _write(path: Path, payload: list[tuple[str, ...]], encoding: str) -> None:
    buffer = path.open("w", encoding=encoding, newline="")
    writer = csv.writer(buffer, delimiter="|", lineterminator="\n")
    writer.writerow(HEADER)
    writer.writerows(payload)
    buffer.close()


@settings(max_examples=25, deadline=None)
@given(payload=rows)
def test_sri_canonical_rows_are_equal_for_utf8_and_cp1252(
    payload: list[tuple[str, ...]],
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        utf8_path = root / "utf8.csv"
        cp1252_path = root / "cp1252.csv"
        _write(utf8_path, payload, "utf-8-sig")
        _write(cp1252_path, payload, "cp1252")

        utf8_result = SriTaxParser().parse(utf8_path, "2024", output_dir=root / "a")
        cp1252_result = SriTaxParser().parse(cp1252_path, "2024", output_dir=root / "b")

        expected = sum(1 for candidate in payload if any(candidate))
        assert utf8_result.row_count == cp1252_result.row_count == expected
        assert utf8_result.path.read_bytes() == cp1252_result.path.read_bytes()
