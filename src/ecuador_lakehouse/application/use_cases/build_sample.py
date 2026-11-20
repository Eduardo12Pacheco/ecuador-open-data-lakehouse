"""Maintainer use case that builds the deterministic offline sample (S3, D10).

The sample is a reduction of the three verified sources: SRI rows are aggregated
to province grain with exact decimal arithmetic, BCE bytes are bundled verbatim
and the twelve INEC index CSVs are repacked into a flat ZIP. Every output is
hashed into ``SAMPLE_MANIFEST.json`` and two runs produce byte-identical files.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import re
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from ecuador_lakehouse.application.ports import SourceFetcher, SourceParser
from ecuador_lakehouse.domain.decoding import decode_bytes
from ecuador_lakehouse.domain.errors import ConfigError, SourceSchemaError
from ecuador_lakehouse.domain.sample import (
    CONTROL_TOTALS_COLUMNS,
    ControlTotal,
    SampleBuildReport,
    SampleFile,
    SampleManifest,
)
from ecuador_lakehouse.domain.sources import Lockfile, SourceFile, SourceId

SRI_SAMPLE_PREFIX = "sri_tax_collection"
BCE_SAMPLE_NAME = "bce_cnt_quarterly.csv.gz"
INEC_SAMPLE_NAME = "inec_cpi_index_2024-12.zip"
SRI_COLUMNS = (
    "ANIO",
    "MES",
    "GRUPO_IMPUESTO",
    "SUBGRUPO_IMPUESTO",
    "IMPUESTO",
    "TIPO_CONTRIBUYENTE",
    "PROVINCIA",
    "VALOR_RECAUDADO",
)
SRI_KEY_COLUMNS = (
    "ANIO",
    "MES",
    "GRUPO_IMPUESTO",
    "SUBGRUPO_IMPUESTO",
    "IMPUESTO",
    "TIPO_CONTRIBUYENTE",
    "PROVINCIA",
)
SRI_CANONICAL_KEY_COLUMNS = (
    "anio",
    "mes_label",
    "grupo",
    "subgrupo",
    "impuesto",
    "tipo_contribuyente",
    "provincia",
)
SRI_CANONICAL_AMOUNT = "valor_raw"
_CENT = Decimal("0.01")
_CPI_MEMBER = re.compile(
    r"^(?:.*/)?ipc_ind_nac_reg_ciud_\d{2}_\d{4}/(?P<number>\d+)\.\s+(?P<name>.+)\.csv$",
    re.IGNORECASE,
)
_MAX_NESTED_DEPTH = 5
_MAX_MEMBER_BYTES = 300 * 1024 * 1024
_MAX_TOTAL_BYTES = 600 * 1024 * 1024
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_CPI_MEMBERS = 12

ATTRIBUTION = """# Bundled sample attribution

This package bundles a reduced, offline copy of three Ecuadorian open-data
sources. The data keeps the license of its publisher (Creative Commons
Attribution); the code of this project is MIT-licensed.

## SRI - Recaudacion de impuestos

- Publisher: Servicio de Rentas Internas (SRI)
- URL: https://descargas.sri.gob.ec/download/datosAbiertos/sri_recaudacion_<YYYY>.csv
- License: Creative Commons Attribution (CKAN `license_id: cc-by`)
- Modification: rows aggregated to province grain; `VALOR_RECAUDADO` summed to
  cents; canton, `GRAN_CONTRIBUYENTE` and `CODIGO_OPERA_FAMILIA` dropped; values
  written as UTF-8 with comma decimals and gzip (mtime 0).

## BCE - Cuentas Nacionales Trimestrales desagregadas

- Publisher: Banco Central del Ecuador (BCE)
- URL: https://www.datosabiertos.gob.ec/dataset/7d5ad4b3-a8f7-42d9-8103-81336a592ea6
- License: Creative Commons Attribution (CKAN `license_id: cc-by`)
- Modification: none; the upstream bytes are bundled verbatim inside a gzip
  container.

## INEC - Indice de Precios al Consumidor (December 2024 vintage, base 2014 = 100)

- Publisher: Instituto Nacional de Estadistica y Censos (INEC)
- URL: https://www.ecuadorencifras.gob.ec/indice-de-precios-al-consumidor-2024/
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)
- Modification: the twelve index CSVs are repacked verbatim into one flat ZIP.

`SAMPLE_MANIFEST.json` records the sha256 of every bundled file and the sha256
of the upstream file it was derived from.
"""


class SampleSourceNotBundledError(ConfigError):
    """A requested partition is not part of the pinned source inventory."""


@dataclass(frozen=True, slots=True)
class BuildSample:
    """Fetch the pinned files and write the deterministic bundled sample."""

    fetcher: SourceFetcher
    lockfile: Lockfile
    parsers: Mapping[SourceId, SourceParser]
    sample_dir: Path
    seed_dir: Path
    builder_version: str

    def execute(
        self,
        years: Sequence[int],
        *,
        accept_new_vintage: bool = False,
    ) -> SampleBuildReport:
        """Build the sample for ``years`` (SRI) plus BCE and INEC, returning a report."""
        selected_years = tuple(sorted(set(years)))
        if not selected_years:
            raise ConfigError("at least one SRI year must be selected")
        files: list[SampleFile] = []
        totals: list[ControlTotal] = []
        cached: list[str] = []
        self.sample_dir.mkdir(parents=True, exist_ok=True)
        self.seed_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="lakehouse-sample-") as tmp:
            scratch = Path(tmp)
            for year in selected_years:
                source_file = self._require(SourceId.SRI_TAX, str(year))
                fetched = self.fetcher.fetch(source_file, accept_new_vintage=accept_new_vintage)
                parsed = self._parse(source_file, fetched.path, scratch)
                target = self.sample_dir / f"{SRI_SAMPLE_PREFIX}_{year}.csv.gz"
                total, rows = _aggregate_sri(parsed, target)
                parsed.unlink(missing_ok=True)
                files.append(
                    _entry(
                        target,
                        source_id=SourceId.SRI_TAX,
                        partition=str(year),
                        rows=rows,
                        derived_from_sha256=fetched.sha256,
                    )
                )
                totals.append(
                    ControlTotal(
                        source_id=SourceId.SRI_TAX,
                        period_year=year,
                        expected_total_usd=total,
                        is_frozen=not source_file.mutable,
                        as_of_date=self.lockfile.checked_at,
                    )
                )
                if fetched.from_cache:
                    cached.append(target.name)

            bce_file = self._require(SourceId.BCE_CNT, "2000Q1-2021Q1")
            bce = self.fetcher.fetch(bce_file, accept_new_vintage=accept_new_vintage)
            bce_payload = bce.path.read_bytes()
            bce_target = self.sample_dir / BCE_SAMPLE_NAME
            _write_gzip(bce_payload, bce_target)
            files.append(
                _entry(
                    bce_target,
                    source_id=SourceId.BCE_CNT,
                    partition=bce_file.partition,
                    rows=_count_bce_rows(bce_payload),
                    derived_from_sha256=bce.sha256,
                )
            )
            if bce.from_cache:
                cached.append(bce_target.name)

            inec_file = self._require(SourceId.INEC_CPI, "2024-12")
            inec = self.fetcher.fetch(inec_file, accept_new_vintage=accept_new_vintage)
            inec_target = self.sample_dir / INEC_SAMPLE_NAME
            _write_cpi_zip(_cpi_members(inec.path), inec_target)
            inec_rows = self._count_cpi_rows(inec_target, inec_file.partition, scratch)
            files.append(
                _entry(
                    inec_target,
                    source_id=SourceId.INEC_CPI,
                    partition=inec_file.partition,
                    rows=inec_rows,
                    derived_from_sha256=inec.sha256,
                )
            )
            if inec.from_cache:
                cached.append(inec_target.name)

        manifest = SampleManifest(
            builder_version=self.builder_version,
            checked_at=self.lockfile.checked_at,
            files=tuple(files),
        )
        (self.sample_dir / "SAMPLE_MANIFEST.json").write_text(
            manifest.to_json_text(), encoding="utf-8"
        )
        (self.sample_dir / "ATTRIBUTION.md").write_text(ATTRIBUTION, encoding="utf-8")
        _write_control_totals(self.seed_dir / "control_totals.csv", totals)
        for entry in manifest.files:
            _verify_written(self.sample_dir / entry.name, entry)
        return SampleBuildReport(
            files=manifest.files,
            control_totals=tuple(totals),
            cached=tuple(cached),
        )

    def _require(self, source_id: SourceId, partition: str) -> SourceFile:
        source_file = self.lockfile.find(source_id, partition)
        if source_file is None:
            raise SampleSourceNotBundledError(
                f"no pinned file for {source_id.value}/{partition} in sources.lock.json"
            )
        return source_file

    def _parse(self, source_file: SourceFile, path: Path, scratch: Path) -> Path:
        parser = self.parsers.get(source_file.source_id)
        if parser is None:
            raise ConfigError(f"no parser registered for source {source_file.source_id.value}")
        parsed = parser.parse(path, source_file.partition, output_dir=scratch)
        return parsed.path

    def _count_cpi_rows(self, path: Path, partition: str, scratch: Path) -> int:
        parser = self.parsers.get(SourceId.INEC_CPI)
        if parser is None:
            raise ConfigError("no parser registered for source inec_cpi")
        parsed = parser.parse(path, partition, output_dir=scratch)
        try:
            return parsed.row_count
        finally:
            parsed.path.unlink(missing_ok=True)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry(
    path: Path,
    *,
    source_id: SourceId,
    partition: str,
    rows: int,
    derived_from_sha256: str,
) -> SampleFile:
    payload = path.read_bytes()
    return SampleFile(
        name=path.name,
        source_id=source_id,
        partition=partition,
        size_bytes=len(payload),
        sha256=_sha256(payload),
        rows=rows,
        derived_from_sha256=derived_from_sha256,
    )


def _verify_written(path: Path, entry: SampleFile) -> None:
    payload = path.read_bytes()
    if len(payload) != entry.size_bytes or _sha256(payload) != entry.sha256:
        raise SourceSchemaError(f"sample output changed after hashing: {entry.name}")


def _aggregate_sri(canonical_csv: Path, target: Path) -> tuple[Decimal, int]:
    groups: dict[tuple[str, ...], Decimal] = {}
    total = Decimal(0)
    with canonical_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = (*SRI_CANONICAL_KEY_COLUMNS, SRI_CANONICAL_AMOUNT)
        missing = [name for name in required if name not in (reader.fieldnames or ())]
        if missing:
            raise SourceSchemaError(
                f"canonical SRI file is missing column(s): {', '.join(missing)}"
            )
        for line_number, row in enumerate(reader, start=2):
            raw = (row[SRI_CANONICAL_AMOUNT] or "").strip()
            if not raw:
                raise SourceSchemaError(f"canonical SRI line {line_number} has an empty amount")
            try:
                value = Decimal(raw.replace(",", "."))
            except InvalidOperation as exc:
                raise SourceSchemaError(
                    f"canonical SRI line {line_number} has an invalid amount: {raw!r}"
                ) from exc
            key = tuple(row[name] for name in SRI_CANONICAL_KEY_COLUMNS)
            groups[key] = groups.get(key, Decimal(0)) + value
            total += value
    ordered = sorted(
        (key, value.quantize(_CENT, rounding=ROUND_HALF_UP)) for key, value in groups.items()
    )
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter="|", lineterminator="\n")
    writer.writerow(SRI_COLUMNS)
    for key, value in ordered:
        writer.writerow([*key, f"{value:.2f}".replace(".", ",")])
    _write_gzip(buffer.getvalue().encode("utf-8"), target)
    return total.quantize(_CENT, rounding=ROUND_HALF_UP), len(ordered)


def _write_gzip(payload: bytes, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with (
        target.open("wb") as handle,
        gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0, compresslevel=9) as gz,
    ):
        gz.write(payload)


def _count_bce_rows(payload: bytes) -> int:
    text, _encoding = decode_bytes(payload)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=";")
    next(reader, None)
    return sum(1 for row in reader if any(cell.strip() for cell in row))


def _cpi_members(archive_path: Path) -> list[tuple[int, str, bytes]]:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = _walk_zip(archive, depth=0)
    except zipfile.BadZipFile as exc:
        raise SourceSchemaError(f"CPI archive {archive_path.name!r} is not a valid ZIP") from exc
    if len(members) != _CPI_MEMBERS:
        raise SourceSchemaError(
            f"CPI archive must contain {_CPI_MEMBERS} index CSVs, found {len(members)}"
        )
    numbers = [number for number, _name, _payload in members]
    if len(set(numbers)) != _CPI_MEMBERS:
        raise SourceSchemaError("CPI archive contains duplicate index numbers")
    return members


def _walk_zip(archive: zipfile.ZipFile, *, depth: int) -> list[tuple[int, str, bytes]]:
    if depth > _MAX_NESTED_DEPTH:
        raise SourceSchemaError(f"CPI archive nests ZIP members deeper than {_MAX_NESTED_DEPTH}")
    members: list[tuple[int, str, bytes]] = []
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if name.lower().endswith(".zip"):
            payload = _read_member(archive, info)
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as nested:
                    members.extend(_walk_zip(nested, depth=depth + 1))
            except zipfile.BadZipFile as exc:
                raise SourceSchemaError(f"nested CPI member {name!r} is not a ZIP") from exc
            continue
        match = _CPI_MEMBER.match(name)
        if match is None:
            continue
        flat_name = f"{match.group('number')}. {match.group('name')}.csv"
        members.append((int(match.group("number")), flat_name, _read_member(archive, info)))
    return members


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if info.file_size > _MAX_MEMBER_BYTES:
        raise SourceSchemaError(f"CPI member {info.filename!r} exceeds the size cap")
    with archive.open(info) as handle:
        payload = handle.read(_MAX_MEMBER_BYTES + 1)
    if len(payload) > _MAX_MEMBER_BYTES:
        raise SourceSchemaError(f"CPI member {info.filename!r} exceeds the size cap")
    return payload


def _write_cpi_zip(members: Sequence[tuple[int, str, bytes]], target: Path) -> None:
    total = sum(len(payload) for _number, _name, payload in members)
    if total > _MAX_TOTAL_BYTES:
        raise SourceSchemaError(f"CPI archive expands to {total} bytes, above the cap")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for _number, name, payload in sorted(members, key=lambda item: item[0]):
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, payload)


def _write_control_totals(path: Path, totals: Sequence[ControlTotal]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CONTROL_TOTALS_COLUMNS)
    for total in sorted(totals, key=lambda item: item.period_year):
        writer.writerow(
            [
                total.source_id.value,
                total.period_year,
                f"{total.expected_total_usd:.2f}",
                "true" if total.is_frozen else "false",
                total.as_of_date,
            ]
        )
    path.write_text(buffer.getvalue(), encoding="utf-8")
