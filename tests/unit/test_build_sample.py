"""Tests for the deterministic sample builder use case (S3, D10)."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.parsers.bce_cnt import BceCntParser
from ecuador_lakehouse.adapters.parsers.inec_cpi import InecCpiParser
from ecuador_lakehouse.adapters.parsers.sri_tax import SriTaxParser
from ecuador_lakehouse.application.ports import FetchResult
from ecuador_lakehouse.application.use_cases.build_sample import (
    BCE_SAMPLE_NAME,
    INEC_SAMPLE_NAME,
    BuildSample,
)
from ecuador_lakehouse.domain.errors import ConfigError, SourceSchemaError
from ecuador_lakehouse.domain.sample import SampleManifest
from ecuador_lakehouse.domain.sources import Lockfile, SourceFile, SourceId

CHECKED_AT = "2026-11-19"
FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "parsers"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_file(source_id: SourceId, partition: str, filename: str) -> SourceFile:
    return SourceFile(
        source_id=source_id,
        partition=partition,
        url=f"https://example.invalid/{filename}",
        filename=filename,
        size_bytes=1,
        sha256="a" * 64,
        mutable=False,
    )


@dataclass
class FakeFetcher:
    paths: dict[tuple[SourceId, str], Path]
    from_cache: bool = False
    accepted: list[bool] = field(default_factory=list)

    def fetch(self, source_file: SourceFile, *, accept_new_vintage: bool = False) -> FetchResult:
        self.accepted.append(accept_new_vintage)
        path = self.paths[(source_file.source_id, source_file.partition)]
        payload = path.read_bytes()
        return FetchResult(
            source_file=source_file,
            path=path,
            sha256=_sha(payload),
            size_bytes=len(payload),
            from_cache=self.from_cache,
            checksum_verified=True,
        )

    def close(self) -> None:
        pass


def _write_sri(path: Path) -> None:
    path.write_text(
        "ANIO|MES|GRUPO_IMPUESTO|SUBGRUPO_IMPUESTO|IMPUESTO|TIPO_CONTRIBUYENTE|"
        "PROVINCIA|VALOR_RECAUDADO\n"
        "2019|01 Enero|IVA|IVA|IVA MENSUAL|SOCIEDADES|GUAYAS|100,10\n"
        "2019|01 Enero|IVA|IVA|IVA MENSUAL|SOCIEDADES|GUAYAS|50,15\n"
        "2019|02 Febrero|RENTA|RENTA|RENTA|PERSONAS NATURALES|PICHINCHA|10,00\n",
        encoding="utf-8",
    )


def _cpi_csv(marker: str) -> bytes:
    text = (
        "Índice de Precios al Consumidor - IPC\n"
        "Base: 2014 = 100\n"
        f"Fuente: {marker}\n"
        "Nivel,Ponderación,Cód. CCIF,Descripción CCIF,ene-15,dic-24\n"
        f'General,"1,000000",0,Índice general,"101,24",110.12\n'
        "Nota: información provisional\n"
    )
    return text.encode("cp1252")


def _write_inec(path: Path) -> None:
    names = [
        "1. NACIONAL.csv",
        "2. REGION SIERRA.csv",
        "3. REGION COSTA.csv",
        "4. Guayaquil.csv",
        "5. Esmeraldas.csv",
        "6. Machala.csv",
        "7. Manta.csv",
        "8. Sto. Domingo.csv",
        "9. Quito.csv",
        "10. Loja.csv",
        "11. Cuenca.csv",
        "12. Ambato.csv",
    ]
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            archive.writestr(f"ipc_ind_nac_reg_ciud_12_2024/{name}", _cpi_csv(name))
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ipc_ind_nac_reg_ciud_12_2024.zip", inner.getvalue())
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Series IPC.zip", nested.getvalue())


def _lockfile() -> Lockfile:
    return Lockfile(
        checked_at=CHECKED_AT,
        licenses={"sri_tax": "cc-by", "bce_cnt": "cc-by", "inec_cpi": "cc-by"},
        files=(
            _source_file(SourceId.SRI_TAX, "2019", "sri_recaudacion_2019.csv"),
            _source_file(SourceId.BCE_CNT, "2000Q1-2021Q1", "cuentastrimestralesdesagregadas.csv"),
            _source_file(SourceId.INEC_CPI, "2024-12", "Tabulados_y_series_historicas_CSV.zip"),
        ),
    )


def _builder(tmp_path: Path, *, from_cache: bool = False) -> tuple[BuildSample, FakeFetcher]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    sri = tmp_path / "sri_2019.csv"
    _write_sri(sri)
    bce = tmp_path / "bce.csv"
    bce.write_bytes((FIXTURES / "bce_mini.csv").read_bytes())
    inec = tmp_path / "inec.zip"
    _write_inec(inec)
    fetcher = FakeFetcher(
        paths={
            (SourceId.SRI_TAX, "2019"): sri,
            (SourceId.BCE_CNT, "2000Q1-2021Q1"): bce,
            (SourceId.INEC_CPI, "2024-12"): inec,
        },
        from_cache=from_cache,
    )
    builder = BuildSample(
        fetcher=fetcher,
        lockfile=_lockfile(),
        parsers={
            SourceId.SRI_TAX: SriTaxParser(),
            SourceId.BCE_CNT: BceCntParser(),
            SourceId.INEC_CPI: InecCpiParser(),
        },
        sample_dir=tmp_path / "sample_data",
        seed_dir=tmp_path / "seeds",
        builder_version="0.1.0",
    )
    return builder, fetcher


def _read_sample_rows(path: Path) -> list[list[str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle, delimiter="|"))


def test_build_sample_writes_aggregated_deterministic_files(tmp_path: Path) -> None:
    builder, fetcher = _builder(tmp_path)

    report = builder.execute([2019])

    names = [entry.name for entry in report.files]
    assert names == sorted(["sri_tax_collection_2019.csv.gz", BCE_SAMPLE_NAME, INEC_SAMPLE_NAME])
    rows = _read_sample_rows(tmp_path / "sample_data" / "sri_tax_collection_2019.csv.gz")
    assert rows[0] == [
        "ANIO",
        "MES",
        "GRUPO_IMPUESTO",
        "SUBGRUPO_IMPUESTO",
        "IMPUESTO",
        "TIPO_CONTRIBUYENTE",
        "PROVINCIA",
        "VALOR_RECAUDADO",
    ]
    assert rows[1:] == [
        ["2019", "01 Enero", "IVA", "IVA", "IVA MENSUAL", "SOCIEDADES", "GUAYAS", "150,25"],
        [
            "2019",
            "02 Febrero",
            "RENTA",
            "RENTA",
            "RENTA",
            "PERSONAS NATURALES",
            "PICHINCHA",
            "10,00",
        ],
    ]
    sri_entry = report.files[2]
    assert sri_entry.rows == 2
    assert sri_entry.size_bytes == (tmp_path / "sample_data" / sri_entry.name).stat().st_size
    assert sri_entry.sha256 == _sha((tmp_path / "sample_data" / sri_entry.name).read_bytes())
    gz_bytes = (tmp_path / "sample_data" / "sri_tax_collection_2019.csv.gz").read_bytes()
    assert gz_bytes[4:8] == b"\x00\x00\x00\x00"
    assert len(fetcher.accepted) == 3


def test_build_sample_writes_manifest_control_totals_and_attribution(tmp_path: Path) -> None:
    builder, _fetcher = _builder(tmp_path)

    report = builder.execute([2019])

    manifest = SampleManifest.from_json_text(
        (tmp_path / "sample_data" / "SAMPLE_MANIFEST.json").read_text(encoding="utf-8")
    )
    assert manifest.files == report.files
    assert manifest.checked_at == CHECKED_AT
    assert manifest.builder_version == "0.1.0"

    seed = (tmp_path / "seeds" / "control_totals.csv").read_text(encoding="utf-8").splitlines()
    assert seed[0] == "source_id,period_year,expected_total_usd,is_frozen,as_of_date"
    assert seed[1] == f"sri_tax,2019,160.25,true,{CHECKED_AT}"

    attribution = (tmp_path / "sample_data" / "ATTRIBUTION.md").read_text(encoding="utf-8")
    assert "Creative Commons" in attribution
    assert "descargas.sri.gob.ec" in attribution
    assert "ecuadorencifras.gob.ec" in attribution


def test_build_sample_is_byte_identical_across_runs(tmp_path: Path) -> None:
    first, _ = _builder(tmp_path / "first")
    second, _ = _builder(tmp_path / "second")

    first.execute([2019])
    second.execute([2019])

    for name in (
        "sri_tax_collection_2019.csv.gz",
        BCE_SAMPLE_NAME,
        INEC_SAMPLE_NAME,
        "SAMPLE_MANIFEST.json",
        "ATTRIBUTION.md",
    ):
        assert (tmp_path / "first" / "sample_data" / name).read_bytes() == (
            tmp_path / "second" / "sample_data" / name
        ).read_bytes(), name


def test_build_sample_reports_cached_files_and_forwards_the_vintage_flag(tmp_path: Path) -> None:
    builder, fetcher = _builder(tmp_path, from_cache=True)

    report = builder.execute([2019], accept_new_vintage=True)

    assert report.cached == tuple(
        sorted(["sri_tax_collection_2019.csv.gz", BCE_SAMPLE_NAME, INEC_SAMPLE_NAME])
    )
    assert report.is_cached("sri_tax_collection_2019.csv.gz") is True
    assert fetcher.accepted == [True, True, True]


def test_build_sample_rejects_an_unknown_year(tmp_path: Path) -> None:
    builder, _fetcher = _builder(tmp_path)

    with pytest.raises(ConfigError, match="2020"):
        builder.execute([2020])


def test_build_sample_rejects_an_incomplete_cpi_archive(tmp_path: Path) -> None:
    builder, fetcher = _builder(tmp_path)
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ipc_ind_nac_reg_ciud_12_2024/1. NACIONAL.csv", _cpi_csv("only"))
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ipc_ind_nac_reg_ciud_12_2024.zip", inner.getvalue())
    fetcher.paths[(SourceId.INEC_CPI, "2024-12")].write_bytes(nested.getvalue())

    with pytest.raises(SourceSchemaError, match="12"):
        builder.execute([2019])


def test_build_sample_bce_bytes_and_rows_come_from_the_upstream_file(tmp_path: Path) -> None:
    builder, _fetcher = _builder(tmp_path)
    report = builder.execute([2019])

    bce_entry = next(entry for entry in report.files if entry.name == BCE_SAMPLE_NAME)
    payload = gzip.decompress((tmp_path / "sample_data" / BCE_SAMPLE_NAME).read_bytes())
    assert payload == (FIXTURES / "bce_mini.csv").read_bytes()
    assert bce_entry.rows == 4
    assert bce_entry.derived_from_sha256 == _sha(payload)
