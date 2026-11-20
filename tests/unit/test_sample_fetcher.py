"""Tests for the bundled-sample fetcher adapter (S2, S3)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.sources.sample_fetcher import SampleSourceFetcher
from ecuador_lakehouse.domain.errors import ChecksumMismatchError, ConfigError
from ecuador_lakehouse.domain.sample import SampleFile, SampleManifest
from ecuador_lakehouse.domain.sources import SourceFile, SourceId


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_file(partition: str = "2019") -> SourceFile:
    return SourceFile(
        source_id=SourceId.SRI_TAX,
        partition=partition,
        url=f"https://descargas.sri.gob.ec/download/datosAbiertos/sri_recaudacion_{partition}.csv",
        filename=f"sri_recaudacion_{partition}.csv",
        size_bytes=10,
        sha256="d" * 64,
    )


def _write_sample(tmp_path: Path) -> tuple[Path, Path, SampleManifest]:
    data_dir = tmp_path / "sample_data"
    data_dir.mkdir()
    payload = b"ANIO|MES\n2019|01 Enero\n"
    (data_dir / "sri_tax_collection_2019.csv.gz").write_bytes(payload)
    manifest = SampleManifest(
        builder_version="0.1.0",
        checked_at="2026-11-19",
        files=(
            SampleFile(
                name="sri_tax_collection_2019.csv.gz",
                source_id=SourceId.SRI_TAX,
                partition="2019",
                size_bytes=len(payload),
                sha256=_sha(payload),
                rows=1,
                derived_from_sha256="e" * 64,
            ),
        ),
    )
    return data_dir, tmp_path / "cache", manifest


def test_sample_fetcher_copies_and_verifies_the_bundled_file(tmp_path: Path) -> None:
    data_dir, cache_dir, manifest = _write_sample(tmp_path)
    fetcher = SampleSourceFetcher(manifest, cache_dir, data_dir=data_dir)

    result = fetcher.fetch(_source_file())

    assert result.path == cache_dir / "sri_tax" / "sri_tax_collection_2019.csv.gz"
    assert result.path.read_bytes() == b"ANIO|MES\n2019|01 Enero\n"
    assert result.sha256 == manifest.files[0].sha256
    assert result.size_bytes == manifest.files[0].size_bytes
    assert result.checksum_verified is True
    assert result.from_cache is False

    second = fetcher.fetch(_source_file())

    assert second.from_cache is True
    assert second.path == result.path


def test_sample_fetcher_rejects_an_unknown_partition(tmp_path: Path) -> None:
    data_dir, cache_dir, manifest = _write_sample(tmp_path)
    fetcher = SampleSourceFetcher(manifest, cache_dir, data_dir=data_dir)

    with pytest.raises(ConfigError, match="not bundled"):
        fetcher.fetch(_source_file(partition="2020"))


def test_sample_fetcher_detects_a_tampered_bundled_file(tmp_path: Path) -> None:
    data_dir, cache_dir, manifest = _write_sample(tmp_path)
    (data_dir / "sri_tax_collection_2019.csv.gz").write_bytes(b"tampered")
    fetcher = SampleSourceFetcher(manifest, cache_dir, data_dir=data_dir)

    with pytest.raises(ChecksumMismatchError, match="checksum mismatch"):
        fetcher.fetch(_source_file())


def test_sample_fetcher_verify_all_reports_the_file_count(tmp_path: Path) -> None:
    data_dir, cache_dir, manifest = _write_sample(tmp_path)
    fetcher = SampleSourceFetcher(manifest, cache_dir, data_dir=data_dir)

    assert fetcher.verify_all() == 1

    (data_dir / "sri_tax_collection_2019.csv.gz").unlink()
    with pytest.raises(ConfigError, match="missing"):
        fetcher.verify_all()
