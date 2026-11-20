"""Integrity tests for the committed offline sample bundle (S3, T5)."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ecuador_lakehouse import __version__
from ecuador_lakehouse.adapters.parsers.inec_cpi import InecCpiParser
from ecuador_lakehouse.adapters.sources.sample_fetcher import SampleSourceFetcher
from ecuador_lakehouse.cli.app import app
from ecuador_lakehouse.container import load_lockfile

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "ecuador_lakehouse"
SAMPLE_DIR = PACKAGE_DIR / "sample_data"
SEED_DIR = PACKAGE_DIR / "dbt_project" / "seeds"
BCE_SHA256 = "b90e0e5a403a44ecd862969b72c6fc900f730e62d7b4cffecaa55116ed81e187"
EXPECTED_SRI_ROWS = {
    2019: 24_035,
    2020: 23_839,
    2021: 25_260,
    2022: 25_889,
    2023: 25_519,
    2024: 24_423,
    2025: 25_348,
    2026: 21_548,
}
SRI_HEADER = (
    "ANIO|MES|GRUPO_IMPUESTO|SUBGRUPO_IMPUESTO|IMPUESTO|TIPO_CONTRIBUYENTE|"
    "PROVINCIA|VALOR_RECAUDADO"
)
runner = CliRunner()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_sample_bundle_manifest_covers_twelve_verified_files() -> None:
    manifest = SampleSourceFetcher.load_manifest()

    assert len(manifest.files) == 12
    assert manifest.builder_version == __version__
    names = [entry.name for entry in manifest.files]
    assert names == sorted(names)
    assert sum(1 for name in names if name.startswith("sri_tax_collection_")) == 10
    assert "bce_cnt_quarterly.csv.gz" in names
    assert "inec_cpi_index_2024-12.zip" in names
    for entry in manifest.files:
        payload = (SAMPLE_DIR / entry.name).read_bytes()
        assert len(payload) == entry.size_bytes, entry.name
        assert _sha256(payload) == entry.sha256, entry.name


def test_sample_bundle_total_size_stays_under_the_budget() -> None:
    total = sum(path.stat().st_size for path in SAMPLE_DIR.iterdir() if path.is_file())

    assert total <= 8_000_000


@pytest.mark.parametrize(("year", "rows"), EXPECTED_SRI_ROWS.items())
def test_sri_sample_has_the_expected_grain_and_row_count(year: int, rows: int) -> None:
    path = SAMPLE_DIR / f"sri_tax_collection_{year}.csv.gz"

    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        lines = list(csv.reader(handle, delimiter="|"))

    assert lines[0] == SRI_HEADER.split("|")
    assert len(lines) - 1 == rows
    assert all(len(line) == 8 for line in lines)
    assert all(line[7].count(",") == 1 and len(line[7].split(",")[1]) == 2 for line in lines[1:])
    assert lines[1:] == sorted(lines[1:])


def test_sri_sample_matches_the_control_totals() -> None:
    totals: dict[int, Decimal] = {}
    with (SEED_DIR / "control_totals.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 10
    for row in rows:
        totals[int(row["period_year"])] = Decimal(row["expected_total_usd"])
        assert row["source_id"] == "sri_tax"
        assert row["as_of_date"] == "2026-11-19"
        assert row["is_frozen"] == ("false" if int(row["period_year"]) == 2026 else "true")

    assert abs(totals[2025] - Decimal("21500900000")) <= Decimal("60000")
    assert abs(totals[2019] - Decimal("14268800000")) <= Decimal("60000")

    sample_total = Decimal(0)
    with gzip.open(SAMPLE_DIR / "sri_tax_collection_2025.csv.gz", "rt", encoding="utf-8") as handle:
        next(handle)
        for line in handle:
            value = line.rsplit("|", 1)[1].strip().replace(",", ".")
            sample_total += Decimal(value)
    assert abs(sample_total - totals[2025]) < Decimal("500")


def test_bce_sample_is_the_verbatim_upstream_file() -> None:
    payload = gzip.decompress((SAMPLE_DIR / "bce_cnt_quarterly.csv.gz").read_bytes())

    assert _sha256(payload) == BCE_SHA256
    text = payload.decode("cp1252")
    assert text.startswith("Tipo Variable;Variable;")
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    assert len(rows) - 1 == 32_470

    manifest = SampleSourceFetcher.load_manifest()
    entry = manifest.find("bce_cnt_quarterly.csv.gz")
    assert entry is not None
    assert entry.rows == 32_470
    assert entry.derived_from_sha256 == BCE_SHA256


def test_inec_sample_repacks_the_twelve_index_csvs_and_parses(tmp_path: Path) -> None:
    archive = SAMPLE_DIR / "inec_cpi_index_2024-12.zip"
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert len(names) == 12
        assert all(name[0].isdigit() and name.endswith(".csv") for name in names)
        for name in names:
            text = bundle.read(name).decode("cp1252")
            assert "Nivel,Ponderación,Cód. CCIF" in text

    parsed = InecCpiParser().parse(archive, "2024-12", output_dir=tmp_path)

    assert parsed.row_count == 911_520
    manifest = SampleSourceFetcher.load_manifest()
    entry = manifest.find("inec_cpi_index_2024-12.zip")
    assert entry is not None
    assert entry.rows == parsed.row_count


def test_sample_attribution_names_the_three_sources_and_licenses() -> None:
    text = (SAMPLE_DIR / "ATTRIBUTION.md").read_text(encoding="utf-8")

    assert "Creative Commons Attribution" in text
    assert "descargas.sri.gob.ec" in text
    assert "datosabiertos.gob.ec" in text
    assert "ecuadorencifras.gob.ec" in text


def test_sample_fetcher_serves_the_packaged_bundle(tmp_path: Path) -> None:
    manifest = SampleSourceFetcher.load_manifest()
    fetcher = SampleSourceFetcher(manifest, tmp_path)

    assert fetcher.verify_all() == 12

    source_file = next(
        entry
        for entry in load_lockfile().files
        if entry.source_id.value == "sri_tax" and entry.partition == "2019"
    )
    result = fetcher.fetch(source_file)
    entry = manifest.find(result.path.name)
    assert entry is not None
    assert result.path.name == "sri_tax_collection_2019.csv.gz"
    assert result.sha256 == entry.sha256


def test_doctor_checks_the_bundled_sample_integrity() -> None:
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "sample: OK (12 files)" in result.output


def test_manifest_declares_the_fetch_date_of_the_snapshot() -> None:
    manifest = SampleSourceFetcher.load_manifest()

    assert manifest.checked_at == "2026-11-19"
