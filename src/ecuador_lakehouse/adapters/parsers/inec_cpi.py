"""Parser for the INEC CPI wide, nested-ZIP tabulados (S5).

The upstream release is a ZIP inside a ZIP inside a ZIP. Each inner folder
holds one CSV per price area with four title rows, a ``Nivel,Ponderación,
Cód. CCIF,Descripción CCIF,ene-15,...`` header and footer notes. The parser
walks the archives in memory, melts the month columns into long rows and keeps
every weight and index value as raw text.

The bundled sample ships the same twelve CSV files in a flat ZIP, which this
parser accepts through the same member matcher.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from ecuador_lakehouse.adapters.parsers._common import (
    canonical_output_path,
    pad_row,
    read_zip_member,
    trim_trailing_empty,
    write_canonical_csv,
)
from ecuador_lakehouse.application.ports import ParsedPartition
from ecuador_lakehouse.domain.decoding import decode_bytes
from ecuador_lakehouse.domain.errors import SourceSchemaError
from ecuador_lakehouse.domain.sources import SourceId
from ecuador_lakehouse.domain.text import normalize_key, parse_es_month_abbr

LABEL = "INEC CPI file"
CANONICAL_COLUMNS = (
    "price_area",
    "nivel",
    "ponderacion_raw",
    "codigo_ccif",
    "descripcion",
    "month_label",
    "value_raw",
)
REQUIRED_COLUMNS = {
    "NIVEL": "Nivel",
    "PONDERACION": "Ponderación",
    "COD CCIF": "Cód. CCIF",
    "DESCRIPCION CCIF": "Descripción CCIF",
}
_MAX_DEPTH = 5
_TOTAL_BYTES_CAP = 600 * 1024 * 1024
_MONTHS_PER_YEAR = 12
_NUMBERED_CSV = re.compile(r"^(?:.*/)?(?P<number>\d+)\.\s+(?P<name>.+)\.csv$", re.IGNORECASE)
_CPI_MEMBER = re.compile(
    r"^(?:.*/)?ipc_ind_nac_reg_ciud_\d{2}_\d{4}/\d+\.\s+.+\.csv$", re.IGNORECASE
)
_FLAT_CPI_MEMBER = re.compile(r"^\d+\.\s+.+\.csv$", re.IGNORECASE)
_VINTAGE_FOLDER = re.compile(
    r"ipc_ind_nac_reg_ciud_(?P<month>\d{2})_(?P<year>\d{4})", re.IGNORECASE
)


class InecCpiParser:
    """Extract the INEC CPI archive into long canonical CSV rows."""

    source_id = SourceId.INEC_CPI

    def parse(
        self, path: Path, partition: str, *, output_dir: Path | None = None
    ) -> ParsedPartition:
        """Write the canonical CSV for one CPI vintage."""
        members = _collect_members(path)
        if not members:
            raise SourceSchemaError(f"{LABEL} contains no CPI member matching the header pattern")
        total_bytes = sum(len(payload) for _name, payload in members)
        if total_bytes > _TOTAL_BYTES_CAP:
            raise SourceSchemaError(
                f"{LABEL} expands to {total_bytes} bytes, above the {_TOTAL_BYTES_CAP} cap"
            )
        vintage = _resolve_vintage(members, partition)
        output = canonical_output_path(output_dir, self.source_id, partition)
        rows = self._iter_rows(members)
        row_count = write_canonical_csv(output, columns=CANONICAL_COLUMNS, rows=rows)
        return ParsedPartition(
            source_id=self.source_id,
            partition=vintage,
            path=output,
            row_count=row_count,
        )

    def _iter_rows(self, members: Sequence[tuple[str, bytes]]) -> Iterator[list[str]]:
        for member_name, payload in members:
            match = _NUMBERED_CSV.match(member_name)
            if match is None:  # pragma: no cover - _collect_members only yields matches
                continue
            price_area = normalize_key(match.group("name"))
            text, _encoding = decode_bytes(payload)
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=",")
            header = _locate_header(reader, member_name)
            yield from _melt_rows(
                reader, member_name=member_name, price_area=price_area, header=header
            )


def _collect_members(path: Path) -> list[tuple[str, bytes]]:
    try:
        with zipfile.ZipFile(path) as archive:
            return _walk_archive(archive, depth=0)
    except zipfile.BadZipFile as exc:
        raise SourceSchemaError(f"{LABEL} {path.name!r} is not a valid ZIP archive") from exc


def _walk_archive(archive: zipfile.ZipFile, *, depth: int) -> list[tuple[str, bytes]]:
    if depth > _MAX_DEPTH:
        raise SourceSchemaError(f"{LABEL} nests ZIP members deeper than {_MAX_DEPTH} levels")
    members: list[tuple[str, bytes]] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if name.lower().endswith(".zip"):
            payload = read_zip_member(archive, info)
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as nested:
                    members.extend(_walk_archive(nested, depth=depth + 1))
            except zipfile.BadZipFile as exc:
                raise SourceSchemaError(
                    f"{LABEL} nested member {name!r} is not a valid ZIP archive"
                ) from exc
        elif name.lower().endswith(".csv") and _is_cpi_member(name):
            members.append((name, read_zip_member(archive, info)))
    return members


def _is_cpi_member(member_name: str) -> bool:
    return bool(_CPI_MEMBER.match(member_name) or _FLAT_CPI_MEMBER.match(member_name))


def _resolve_vintage(members: Sequence[tuple[str, bytes]], fallback: str) -> str:
    vintages = {
        vintage for name, _payload in members if (vintage := _member_vintage(name)) is not None
    }
    if len(vintages) > 1:
        raise SourceSchemaError(f"{LABEL} mixes several vintages: {', '.join(sorted(vintages))}")
    return vintages.pop() if vintages else fallback


def _member_vintage(member_name: str) -> str | None:
    match = _VINTAGE_FOLDER.search(member_name)
    if match is None:
        return None
    month = int(match.group("month"))
    year = int(match.group("year"))
    if not 1 <= month <= _MONTHS_PER_YEAR:
        raise SourceSchemaError(f"{LABEL} member {member_name!r} has an invalid month {month}")
    return f"{year}-{month:02d}"


@dataclass(frozen=True, slots=True)
class _MemberHeader:
    """Column layout shared by every data row of one CPI member."""

    positions: dict[str, int]
    month_columns: tuple[tuple[int, str], ...]

    @property
    def width(self) -> int:
        return len(self.positions) + len(self.month_columns)


def _locate_header(reader: Iterator[list[str]], member_name: str) -> _MemberHeader:
    for row in reader:
        cells = trim_trailing_empty([cell.strip() for cell in row])
        if not cells:
            continue
        if normalize_key(cells[0]) == "NIVEL":
            return _validate_header(cells, member_name)
    raise SourceSchemaError(f"{LABEL} member {member_name!r} is missing the 'Nivel' header row")


def _validate_header(header: Sequence[str], member_name: str) -> _MemberHeader:
    positions: dict[str, int] = {}
    month_columns: list[tuple[int, str]] = []
    for index, name in enumerate(header):
        key = normalize_key(name)
        if key in REQUIRED_COLUMNS:
            if key in positions:
                raise SourceSchemaError(
                    f"{LABEL} member {member_name!r} has a duplicate column: {name!r}"
                )
            positions[key] = index
            continue
        try:
            parse_es_month_abbr(name)
        except ValueError as exc:
            raise SourceSchemaError(
                f"{LABEL} member {member_name!r} header has unknown column(s): {name}"
            ) from exc
        month_columns.append((index, name))
    missing = [upstream for key, upstream in REQUIRED_COLUMNS.items() if key not in positions]
    if missing:
        raise SourceSchemaError(
            f"{LABEL} member {member_name!r} is missing required column(s): {', '.join(missing)}"
        )
    if not month_columns:
        raise SourceSchemaError(f"{LABEL} member {member_name!r} has no month columns")
    return _MemberHeader(positions=positions, month_columns=tuple(month_columns))


def _melt_rows(
    reader: Iterator[list[str]],
    *,
    member_name: str,
    price_area: str,
    header: _MemberHeader,
) -> Iterator[list[str]]:
    label = f"{LABEL} member {member_name!r}"
    for offset, raw in enumerate(reader, start=1):
        if not raw:
            break
        first_cell = raw[0].strip()
        if not first_cell or first_cell.upper().startswith(("NOTA", "FUENTE")):
            break
        row = pad_row(raw, header.width, line_number=offset, label=label)
        nivel = row[header.positions["NIVEL"]].strip()
        ponderacion = row[header.positions["PONDERACION"]].strip()
        codigo = row[header.positions["COD CCIF"]].strip()
        descripcion = row[header.positions["DESCRIPCION CCIF"]].strip()
        for index, month_label in header.month_columns:
            value = row[index].strip()
            if not value:
                continue
            yield [price_area, nivel, ponderacion, codigo, descripcion, month_label, value]
