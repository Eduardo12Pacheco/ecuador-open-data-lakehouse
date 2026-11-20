"""Integration tests for artifact publishing, verification and contract checks (S14, S15)."""

from __future__ import annotations

import hashlib
import json
import shutil
from importlib import resources
from pathlib import Path

import duckdb
import jsonschema
import pytest

from ecuador_lakehouse.adapters.artifact.publisher import DuckDbArtifactPublisher
from ecuador_lakehouse.adapters.artifact.verifier import DuckDbArtifactVerifier
from ecuador_lakehouse.application.use_cases.publish import CheckContract, PublishArtifact
from ecuador_lakehouse.application.use_cases.verify import VerifyArtifact
from ecuador_lakehouse.domain import quality as q
from ecuador_lakehouse.domain.contract import ArtifactContract
from ecuador_lakehouse.domain.errors import ArtifactVerificationError
from ecuador_lakehouse.domain.manifest import ArtifactManifest, FileRef, SourceRef
from ecuador_lakehouse.domain.sources import SourceId

from .conftest import StagingBuild

EXPECTED_TABLES = 14


def load_contract() -> ArtifactContract:
    text = (
        resources.files("ecuador_lakehouse")
        .joinpath("artifact_contract.json")
        .read_text(encoding="utf-8")
    )
    return ArtifactContract.from_json_text(text)


def quality_summary() -> q.QualitySummary:
    return q.QualitySummary.from_outcomes(
        [
            q.TestOutcome(name="not_null_dim_date", status=q.TestStatus.PASS),
            q.TestOutcome(name="unique_dim_date", status=q.TestStatus.PASS),
            q.TestOutcome(name="unit_case", status=q.TestStatus.PASS, kind=q.TestKind.UNIT),
        ]
    )


def provenance() -> tuple[SourceRef, ...]:
    return (
        SourceRef(
            source_id=SourceId.SRI_TAX,
            url="https://descargas.sri.gob.ec/download/datosAbiertos/sri_recaudacion_2019.csv",
            license_id="cc-by",
            files=(FileRef(name="sri_tax_collection_2019.csv.gz", sha256="a" * 64),),
        ),
    )


def publish(build: StagingBuild, out_dir: Path) -> Path:
    use_case = PublishArtifact(
        store=DuckDbArtifactPublisher(),
        transformer=build.transformer,
        contract=load_contract(),
        warehouse_path=build.warehouse_path,
        out_dir=out_dir,
        built_from=provenance(),
        generator="ecuador-open-data-lakehouse/0.1.0",
        data_mode="sample",
        attribution="Test attribution.",
    )
    result = use_case.execute(quality=quality_summary())
    return result.artifact_dir


@pytest.fixture(scope="module")
def artifact(marts_build: StagingBuild, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Publish the fully built sample warehouse once for this module."""
    return publish(marts_build, tmp_path_factory.mktemp("artifact-out"))


def test_publish_writes_the_documented_layout(artifact: Path) -> None:
    assert artifact.name == "ecuador-lakehouse-1.0.0"
    assert (artifact / "ecuador_lakehouse.duckdb").is_file()
    assert (artifact / "manifest.json").is_file()
    assert (artifact / "SHA256SUMS").is_file()
    assert (artifact / "ATTRIBUTION.md").is_file()
    parquet = sorted((artifact / "parquet").glob("*.parquet"))
    assert len(parquet) == EXPECTED_TABLES


def test_publish_writes_only_the_marts_and_meta_schemas(artifact: Path) -> None:
    with duckdb.connect(str(artifact / "ecuador_lakehouse.duckdb"), read_only=True) as connection:
        schemas = {
            row[0]
            for row in connection.execute(
                "select schema_name from information_schema.schemata"
            ).fetchall()
        }
        marts = {
            row[0]
            for row in connection.execute(
                "select table_name from information_schema.tables where table_schema = 'marts'"
            ).fetchall()
        }
        build_info = connection.execute("select count(*) from meta.build_info").fetchone()

    assert {"marts", "meta"} <= schemas
    assert not {"raw", "staging", "intermediate"} & schemas
    assert len(marts) == EXPECTED_TABLES
    assert build_info is not None
    assert build_info[0] == 1


def test_manifest_is_valid_against_the_committed_json_schema(artifact: Path) -> None:
    schema_path = Path("docs/schemas/manifest.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))

    jsonschema.validate(instance=manifest, schema=schema)


def test_manifest_describes_every_table_and_contract_column(artifact: Path) -> None:
    manifest = ArtifactManifest.from_json_text(
        (artifact / "manifest.json").read_text(encoding="utf-8")
    )
    contract = load_contract()

    assert len(manifest.tables) == EXPECTED_TABLES
    assert manifest.artifact_version == contract.contract_version
    assert manifest.quality.tests_total == 2
    assert manifest.quality.unit_tests_total == 1
    for table in manifest.tables:
        contract_table = contract.find_table(table.name)
        assert contract_table is not None
        assert table.grain == contract_table.grain
        assert [(column.name, column.type) for column in table.columns] == [
            (column.name, column.type) for column in contract_table.columns
        ]
        assert table.row_count >= 0
        assert table.parquet_file == f"parquet/{table.name}.parquet"
        assert len(table.content_sha256) == 64


def test_verify_accepts_the_published_artifact(artifact: Path) -> None:
    result = VerifyArtifact(store=DuckDbArtifactVerifier()).execute(artifact)

    assert result.table_count == EXPECTED_TABLES


def test_verify_detects_a_tampered_parquet_file(artifact: Path, tmp_path: Path) -> None:
    tampered = tmp_path / artifact.name
    _copy_tree(artifact, tampered)
    parquet = tampered / "parquet" / "dim_date.parquet"
    data = bytearray(parquet.read_bytes())
    data[len(data) // 2] ^= 0xFF
    parquet.write_bytes(bytes(data))

    with pytest.raises(ArtifactVerificationError, match=r"SHA-256|checksum|sha256"):
        VerifyArtifact(store=DuckDbArtifactVerifier()).execute(tampered)


def test_verify_detects_a_removed_table(artifact: Path, tmp_path: Path) -> None:
    tampered = tmp_path / artifact.name
    _copy_tree(artifact, tampered)
    (tampered / "parquet" / "mart_tax_to_gdp_annual.parquet").unlink()

    with pytest.raises(ArtifactVerificationError, match="mart_tax_to_gdp_annual"):
        VerifyArtifact(store=DuckDbArtifactVerifier()).execute(tampered)


def test_verify_detects_rows_changed_in_the_artifact_database(
    artifact: Path, tmp_path: Path
) -> None:
    tampered = tmp_path / artifact.name
    _copy_tree(artifact, tampered)
    database = tampered / "ecuador_lakehouse.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("update marts.dim_price_area set price_area_name = 'TAMPERED' where 1=1")
    # An attacker who can rewrite the checksums still cannot forge the logical
    # fingerprint stored in the manifest.
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    sums_path = tampered / "SHA256SUMS"
    lines = [
        f"{digest}  ecuador_lakehouse.duckdb"
        if line.endswith("  ecuador_lakehouse.duckdb")
        else line
        for line in sums_path.read_text(encoding="utf-8").splitlines()
    ]
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ArtifactVerificationError, match=r"content|fingerprint"):
        VerifyArtifact(store=DuckDbArtifactVerifier()).execute(tampered)


def test_contract_check_accepts_the_published_schema(marts_build: StagingBuild) -> None:
    checker = CheckContract(
        store=DuckDbArtifactPublisher(),
        contract=load_contract(),
    )

    result = checker.execute(marts_build.warehouse_path)

    assert result.diff.required_bump == "none"
    assert len(result.current_table_names) == EXPECTED_TABLES


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination)
