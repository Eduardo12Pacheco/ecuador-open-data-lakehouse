"""Unit tests for the publish use case policy and dbt manifest joins (S14)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ecuador_lakehouse.application.ports import PublishRequest, PublishResult, VerifyResult
from ecuador_lakehouse.application.use_cases.publish import PublishArtifact, table_specs
from ecuador_lakehouse.domain import quality as q
from ecuador_lakehouse.domain.contract import (
    ArtifactContract,
    ContractColumn,
    ContractTable,
)
from ecuador_lakehouse.domain.errors import ConfigError, QualityGateError
from ecuador_lakehouse.domain.manifest import (
    ArtifactManifest,
    ArtifactVersion,
    ColumnInfo,
    FileRef,
    QualityCounts,
    SourceRef,
    TableInfo,
)
from ecuador_lakehouse.domain.sources import SourceId

SHA = "a" * 64


def contract() -> ArtifactContract:
    return ArtifactContract(
        contract_version=ArtifactVersion(1, 0, 0),
        artifact_name="ecuador-lakehouse",
        tables=(
            ContractTable(
                name="dim_date",
                kind="dim",
                grain="month",
                columns=(ContractColumn(name="month_key", type="INTEGER"),),
            ),
        ),
    )


def manifest(**columns: Any) -> dict[str, Any]:
    return {
        "nodes": {
            "model.ecuador_lakehouse.dim_date": {
                "resource_type": "model",
                "name": "dim_date",
                "columns": {
                    "month_key": {
                        "name": "month_key",
                        "description": "Month key.",
                        **columns,
                    }
                },
            }
        }
    }


def summary(*, ok: bool = True) -> q.QualitySummary:
    status = q.TestStatus.PASS if ok else q.TestStatus.FAIL
    return q.QualitySummary.from_outcomes(
        [
            q.TestOutcome(name="not_null_month_key", status=status),
            q.TestOutcome(name="unit_case", status=q.TestStatus.PASS, kind=q.TestKind.UNIT),
        ]
    )


class FakeTransformer:
    def __init__(self, manifest_data: dict[str, Any], result: q.QualitySummary) -> None:
        self.manifest_data = manifest_data
        self.result = result
        self.test_calls = 0

    def test(self, *, select: str | None = None) -> q.QualitySummary:
        self.test_calls += 1
        return self.result

    def manifest(self) -> dict[str, Any]:
        return self.manifest_data

    def seed_and_run(self, *, select: str | None = None) -> None:
        return None

    def docs(self) -> Path:
        return Path("index.html")

    def close(self) -> None:
        return None


class FakeStore:
    def __init__(self) -> None:
        self.requests: list[PublishRequest] = []

    def publish(self, request: PublishRequest) -> PublishResult:
        self.requests.append(request)
        return PublishResult(artifact_dir=request.out_dir, manifest=_artifact_manifest())

    def verify(self, artifact_dir: Path) -> VerifyResult:
        raise NotImplementedError

    def read_schema(self, warehouse_path: Path, *, base: ArtifactContract) -> ArtifactContract:
        raise NotImplementedError


def _artifact_manifest() -> ArtifactManifest:
    return ArtifactManifest(
        artifact_name="ecuador-lakehouse",
        artifact_version=ArtifactVersion(1, 0, 0),
        generator="ecuador-open-data-lakehouse/0.1.0",
        duckdb_version="2.0.0",
        dbt_core_version="1.12.7",
        data_mode="sample",
        built_from=(
            SourceRef(
                source_id=SourceId.SRI_TAX,
                url="https://example.test/sri",
                license_id="cc-by",
                files=(FileRef(name="sri.csv.gz", sha256=SHA),),
            ),
        ),
        tables=(
            TableInfo(
                name="dim_date",
                kind="dim",
                grain="month",
                row_count=1,
                columns=(ColumnInfo(name="month_key", type="INTEGER", description="Month key."),),
                content_sha256=SHA,
                parquet_file="parquet/dim_date.parquet",
            ),
        ),
        quality=QualityCounts(
            tests_total=1, tests_passed=1, unit_tests_total=1, unit_tests_passed=1
        ),
        attribution="See ATTRIBUTION.md.",
    )


def use_case(transformer: FakeTransformer, store: FakeStore, tmp_path: Path) -> PublishArtifact:
    return PublishArtifact(
        store=store,
        transformer=transformer,  # type: ignore[arg-type]
        contract=contract(),
        warehouse_path=tmp_path / "warehouse.duckdb",
        out_dir=tmp_path / "out",
        built_from=(
            SourceRef(
                source_id=SourceId.SRI_TAX,
                url="https://example.test/sri",
                license_id="cc-by",
                files=(FileRef(name="sri.csv.gz", sha256=SHA),),
            ),
        ),
        generator="ecuador-open-data-lakehouse/0.1.0",
        data_mode="sample",
        attribution="See ATTRIBUTION.md.",
    )


def test_publish_passes_the_quality_counts_and_table_specs(tmp_path: Path) -> None:
    transformer = FakeTransformer(manifest(), summary())
    store = FakeStore()

    result = use_case(transformer, store, tmp_path).execute(quality=summary())

    assert result.table_count == 1
    assert transformer.test_calls == 0
    request = store.requests[0]
    assert request.quality == QualityCounts(
        tests_total=1, tests_passed=1, unit_tests_total=1, unit_tests_passed=1
    )
    assert request.table_specs["dim_date"].descriptions == {"month_key": "Month key."}
    assert request.source_warehouse == tmp_path / "warehouse.duckdb"
    assert request.duckdb_version
    assert request.dbt_core_version


def test_publish_runs_the_quality_gate_when_no_summary_is_given(tmp_path: Path) -> None:
    transformer = FakeTransformer(manifest(), summary())
    store = FakeStore()

    use_case(transformer, store, tmp_path).execute()

    assert transformer.test_calls == 1
    assert len(store.requests) == 1


def test_publish_refuses_a_closed_quality_gate(tmp_path: Path) -> None:
    transformer = FakeTransformer(manifest(), summary(ok=False))
    store = FakeStore()

    with pytest.raises(QualityGateError, match="not_null_month_key"):
        use_case(transformer, store, tmp_path).execute(quality=summary(ok=False))

    assert store.requests == []


def test_table_specs_requires_every_model_and_column_description() -> None:
    specs = table_specs(contract(), manifest())
    assert specs["dim_date"].kind == "dim"

    with pytest.raises(ConfigError, match="dim_date"):
        table_specs(contract(), {"nodes": {}})
    with pytest.raises(ConfigError, match="month_key"):
        table_specs(contract(), manifest(description="   "))
