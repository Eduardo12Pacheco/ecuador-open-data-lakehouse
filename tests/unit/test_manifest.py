"""Tests for the artifact manifest value objects and codec (S14)."""

from __future__ import annotations

import pytest

from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.manifest import (
    SCHEMA_VERSION,
    ArtifactManifest,
    ArtifactVersion,
    ColumnInfo,
    FileRef,
    QualityCounts,
    SourceRef,
    TableInfo,
)
from ecuador_lakehouse.domain.sources import SourceId

SHA_A = "a" * 64
SHA_B = "b" * 64


def _table(name: str = "dim_date", *, kind: str = "dim") -> TableInfo:
    return TableInfo(
        name=name,
        kind=kind,
        grain="month",
        row_count=322,
        columns=(
            ColumnInfo(name="month_key", type="INTEGER", description="Month key."),
            ColumnInfo(name="month_start_date", type="DATE", description="First day."),
        ),
        content_sha256=SHA_A,
        parquet_file=f"parquet/{name}.parquet",
    )


def _manifest(**overrides: object) -> ArtifactManifest:
    values: dict[str, object] = {
        "artifact_name": "ecuador-lakehouse",
        "artifact_version": ArtifactVersion(1, 0, 0),
        "generator": "ecuador-open-data-lakehouse/0.1.0",
        "duckdb_version": "2.0.0",
        "dbt_core_version": "1.12.7",
        "data_mode": "sample",
        "built_from": (
            SourceRef(
                source_id=SourceId.SRI_TAX,
                url="https://example.test/sri",
                license_id="cc-by",
                files=(FileRef(name="sri.csv.gz", sha256=SHA_B),),
            ),
        ),
        "tables": (_table(),),
        "quality": QualityCounts(
            tests_total=264, tests_passed=264, unit_tests_total=11, unit_tests_passed=11
        ),
        "attribution": "See ATTRIBUTION.md.",
    }
    values.update(overrides)
    return ArtifactManifest(**values)  # type: ignore[arg-type]


def test_artifact_version_parses_and_renders_semver() -> None:
    version = ArtifactVersion.parse("1.2.3")

    assert (version.major, version.minor, version.patch) == (1, 2, 3)
    assert str(version) == "1.2.3"


@pytest.mark.parametrize("text", ["1.2", "1.2.3.4", "v1.2.3", "1.-2.3", "", "one.two.three"])
def test_artifact_version_rejects_malformed_text(text: str) -> None:
    with pytest.raises(ConfigError):
        ArtifactVersion.parse(text)


def test_artifact_version_bumps_reset_lower_parts() -> None:
    version = ArtifactVersion(1, 2, 3)

    assert str(version.bump("major")) == "2.0.0"
    assert str(version.bump("minor")) == "1.3.0"
    assert str(version.bump("patch")) == "1.2.4"


def test_artifact_version_is_ordered() -> None:
    assert ArtifactVersion(1, 2, 3) < ArtifactVersion(1, 3, 0)
    assert ArtifactVersion(2, 0, 0) > ArtifactVersion(1, 9, 9)


def test_manifest_round_trips_through_its_deterministic_codec() -> None:
    manifest = _manifest()

    text = manifest.to_json_text()

    assert text.endswith("\n")
    assert f'"schema_version": "{SCHEMA_VERSION}"' in text
    assert ArtifactManifest.from_json_text(text) == manifest
    assert manifest.to_json_text() == text


def test_manifest_sorts_tables_and_source_files_by_name() -> None:
    manifest = _manifest(
        tables=(_table("mart_b", kind="mart"), _table("dim_a")),
        built_from=(
            SourceRef(
                source_id=SourceId.SRI_TAX,
                url="https://example.test/sri",
                license_id="cc-by",
                files=(FileRef(name="z.csv", sha256=SHA_A), FileRef(name="a.csv", sha256=SHA_B)),
            ),
        ),
    )

    assert [table.name for table in manifest.tables] == ["dim_a", "mart_b"]
    assert [entry.name for entry in manifest.built_from[0].files] == ["a.csv", "z.csv"]
    assert manifest.find_table("mart_b") is not None
    assert manifest.find_table("missing") is None


def test_manifest_rejects_unknown_schema_versions() -> None:
    payload = _manifest().to_json_text().replace(f'"{SCHEMA_VERSION}"', '"9.9"')

    with pytest.raises(ConfigError, match="schema_version"):
        ArtifactManifest.from_json_text(payload)


def test_manifest_rejects_duplicate_tables() -> None:
    with pytest.raises(ConfigError, match="duplicate"):
        _manifest(tables=(_table("dim_date"), _table("dim_date")))


def test_manifest_rejects_invalid_quality_counts() -> None:
    with pytest.raises(ValueError, match="passed"):
        QualityCounts(tests_total=3, tests_passed=4, unit_tests_total=1, unit_tests_passed=1)


def test_table_info_validates_kind_schema_and_parquet_path() -> None:
    with pytest.raises(ValueError, match="kind"):
        _table(kind="other")
    with pytest.raises(ValueError, match="parquet"):
        TableInfo(
            name="dim_date",
            kind="dim",
            grain="month",
            row_count=1,
            columns=(ColumnInfo(name="a", type="INTEGER", description="A."),),
            content_sha256=SHA_A,
            parquet_file="../escape.parquet",
        )
    with pytest.raises(ValueError, match="content_sha256"):
        TableInfo(
            name="dim_date",
            kind="dim",
            grain="month",
            row_count=1,
            columns=(ColumnInfo(name="a", type="INTEGER", description="A."),),
            content_sha256="not-a-sha",
            parquet_file="parquet/dim_date.parquet",
        )


def test_column_info_requires_a_description() -> None:
    with pytest.raises(ValueError, match="description"):
        ColumnInfo(name="a", type="INTEGER", description=" ")


def test_manifest_requires_a_non_empty_attribution() -> None:
    with pytest.raises(ValueError, match="attribution"):
        _manifest(attribution="")
