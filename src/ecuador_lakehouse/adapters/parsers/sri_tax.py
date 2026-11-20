"""Header-driven parser for SRI monthly tax-collection files (S5, D13).

Upstream files use ``|`` as delimiter, comma decimals and a Spanish month
label (``01 Enero``). They change encoding across years (UTF-8 with BOM until
2022, cp1252 from 2023) and older files lack ``CANTON``; both quirks are
handled here while every value stays as raw text for the dbt typing layer.
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

LABEL = "SRI tax file"
DELIMITER = "|"
REQUIRED_COLUMNS = (
    "ANIO",
    "MES",
    "GRUPO_IMPUESTO",
    "SUBGRUPO_IMPUESTO",
    "IMPUESTO",
    "TIPO_CONTRIBUYENTE",
    "PROVINCIA",
    "VALOR_RECAUDADO",
)
OPTIONAL_COLUMNS = ("CANTON",)
IGNORED_COLUMNS = ("GRAN_CONTRIBUYENTE", "CODIGO_OPERA_FAMILIA")
CANONICAL_COLUMNS = (
    "anio",
    "mes_label",
    "grupo",
    "subgrupo",
    "impuesto",
    "tipo_contribuyente",
    "provincia",
    "canton",
    "valor_raw",
)


class SriTaxParser:
    """Extract an SRI yearly file into canonical CSV rows."""

    source_id = SourceId.SRI_TAX

    def parse(
        self, path: Path, partition: str, *, output_dir: Path | None = None
    ) -> ParsedPartition:
        """Write the canonical CSV for one SRI yearly partition."""
        output = canonical_output_path(output_dir, self.source_id, partition)
        with open_source_text(path) as handle:
            reader = csv.reader(handle, delimiter=DELIMITER)
            header = trim_trailing_empty(first_non_empty_row(reader, label=LABEL))
            positions = require_columns(
                header,
                required=REQUIRED_COLUMNS,
                optional=OPTIONAL_COLUMNS,
                ignored=IGNORED_COLUMNS,
                label=LABEL,
            )
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
                row[positions["ANIO"]],
                row[positions["MES"]],
                row[positions["GRUPO_IMPUESTO"]],
                row[positions["SUBGRUPO_IMPUESTO"]],
                row[positions["IMPUESTO"]],
                row[positions["TIPO_CONTRIBUYENTE"]],
                row[positions["PROVINCIA"]],
                row[positions["CANTON"]] if "CANTON" in positions else "",
                row[positions["VALOR_RECAUDADO"]],
            ]
