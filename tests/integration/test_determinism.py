"""Determinism: two fresh sample builds publish identical logical content (S15)."""

from __future__ import annotations

from pathlib import Path

from ecuador_lakehouse.config import Settings
from ecuador_lakehouse.container import build_container
from ecuador_lakehouse.domain.manifest import ArtifactManifest

EXPECTED_TABLES = 14


def _build_and_publish(home: Path, out: Path) -> ArtifactManifest:
    container = build_container(Settings(home=home, mode="sample"), publish_out=out)
    try:
        report = container.pipeline.run()
    finally:
        container.close()
    assert report.ok
    artifact_dir = out / "ecuador-lakehouse-1.0.0"
    return ArtifactManifest.from_json_text(
        (artifact_dir / "manifest.json").read_text(encoding="utf-8")
    )


def test_two_fresh_sample_builds_publish_identical_content_hashes(
    tmp_path: Path,
) -> None:
    first = _build_and_publish(tmp_path / "home-one", tmp_path / "out-one")
    second = _build_and_publish(tmp_path / "home-two", tmp_path / "out-two")

    first_hashes = {table.name: table.content_sha256 for table in first.tables}
    second_hashes = {table.name: table.content_sha256 for table in second.tables}

    assert len(first_hashes) == EXPECTED_TABLES
    assert first_hashes == second_hashes
    assert first.to_json_text() == second.to_json_text()
