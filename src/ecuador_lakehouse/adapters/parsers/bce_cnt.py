"""Parser for BCE quarterly national-accounts files (S5).

The upstream file is ``;``-delimited cp1252 with comma thousands separators,
empty values and negative numbers. Every field is kept as raw text; the dbt
staging layer turns ``valor_raw`` into a typed ``BIGINT``.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

from ecuador_lakehouse.adapters.parsers._common import (
    canonical_output_path,
    first_non_empty_row,
    open_source_text,
    pad_row,
    require_columns,
    trim_trailing_empty,
    write_canonical_csv,
)
from ecuador_lakehouse.application.ports import ParsedPartition
from ecuador_lakehouse.domain.sources import SourceId

LABEL = "BCE national accounts file"
DELIMITER = ";"
REQUIRED_COLUMNS = (
    "Tipo Variable",
    "Variable",
    "Código Industria-Producto",
    "Industrias-Productos",
    "Unidades",
    "Año",
    "Trimestre",
    "Valor",
)
CANONICAL_COLUMNS = (
    "tipo_variable",
    "variable",
    "codigo",
    "descripcion",
    "unidades",
    "anio",
    "trimestre",
    "valor_raw",
)


class BceCntParser:
    """Extract the BCE national-accounts CSV into canonical rows."""

    source_id = SourceId.BCE_CNT

    def parse(
        self, path: Path, partition: str, *, output_dir: Path | None = None
    ) -> ParsedPartition:
        """Write the canonical CSV for the BCE partition."""
        output = canonical_output_path(output_dir, self.source_id, partition)
        with open_source_text(path) as handle:
            reader = csv.reader(handle, delimiter=DELIMITER)
            header = trim_trailing_empty(first_non_empty_row(reader, label=LABEL))
            positions = require_columns(header, required=REQUIRED_COLUMNS, label=LABEL)
            rows = self._iter_rows(reader, positions, len(header))
            row_count = write_canonical_csv(output, columns=CANONICAL_COLUMNS, rows=rows)
        return ParsedPartition(
            source_id=self.source_id,
            partition=partition,
            path=output,
            row_count=row_count,
        )

    @staticmethod
    def _iter_rows(
        reader: Iterator[list[str]], positions: dict[str, int], width: int
    ) -> Iterator[list[str]]:
        for line_number, raw in enumerate(reader, start=2):
            if not any(cell.strip() for cell in raw):
                continue
            row = pad_row(raw, width, line_number=line_number, label=LABEL)
            yield [
                row[positions["Tipo Variable"]],
                row[positions["Variable"]],
                row[positions["Código Industria-Producto"]],
                row[positions["Industrias-Productos"]],
                row[positions["Unidades"]],
                row[positions["Año"]],
                row[positions["Trimestre"]],
                row[positions["Valor"]],
            ]
