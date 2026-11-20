"""Publish and contract-check use cases (S14).

The use case owns the policy: publishing runs (or reuses) the quality gate,
reads the dbt manifest for column descriptions, assembles the typed request and
delegates all filesystem and DuckDB work to the ``ArtifactStore`` adapter.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

from ecuador_lakehouse.application.ports import (
    ArtifactStore,
    PublishRequest,
    PublishResult,
    TableSpec,
    Transformer,
)
from ecuador_lakehouse.domain.contract import ArtifactContract, ContractDiff, diff_contracts
from ecuador_lakehouse.domain.errors import ConfigError, QualityGateError
from ecuador_lakehouse.domain.manifest import ArtifactVersion, QualityCounts, SourceRef
from ecuador_lakehouse.domain.quality import QualitySummary


@dataclass(frozen=True, slots=True)
class ContractCheckResult:
    """Outcome of comparing the committed contract with the warehouse schema."""

    committed_version: ArtifactVersion
    current_table_names: tuple[str, ...]
    diff: ContractDiff

    @property
    def ok(self) -> bool:
        """Whether the committed contract still describes the warehouse."""
        return self.diff.required_bump == "none"


class PublishArtifact:
    """Publish the marts as a versioned artifact once the quality gate is open."""

    def __init__(  # noqa: PLR0913 - explicit composition-root wiring
        self,
        *,
        store: ArtifactStore,
        transformer: Transformer,
        contract: ArtifactContract,
        warehouse_path: Path,
        out_dir: Path,
        built_from: tuple[SourceRef, ...],
        generator: str,
        data_mode: str,
        attribution: str,
    ) -> None:
        self._store = store
        self._transformer = transformer
        self._contract = contract
        self._warehouse_path = Path(warehouse_path)
        self._out_dir = Path(out_dir)
        self._built_from = built_from
        self._generator = generator
        self._data_mode = data_mode
        self._attribution = attribution

    @property
    def out_dir(self) -> Path:
        """Directory where ``build --publish`` writes the artifact."""
        return self._out_dir

    def execute(self, *, quality: QualitySummary | None = None) -> PublishResult:
        """Run the quality gate when needed and publish the artifact."""
        summary = quality if quality is not None else self._transformer.test()
        if not summary.ok:
            failed = ", ".join(summary.failed_names)
            raise QualityGateError(f"quality gate failed ({summary.failed} failed): {failed}")
        manifest = self._transformer.manifest()
        specs = table_specs(self._contract, manifest)
        request = _request(
            self._warehouse_path,
            self._out_dir,
            self._contract,
            specs,
            built_from=self._built_from,
            generator=self._generator,
            data_mode=self._data_mode,
            attribution=self._attribution,
            quality=QualityCounts(
                tests_total=summary.data_tests_total,
                tests_passed=summary.data_tests_passed,
                unit_tests_total=summary.unit_tests_total,
                unit_tests_passed=summary.unit_tests_passed,
            ),
        )
        return self._store.publish(request)


class CheckContract:
    """Compare the committed contract with the schema materialized in a warehouse."""

    def __init__(self, *, store: ArtifactStore, contract: ArtifactContract) -> None:
        self._store = store
        self._contract = contract

    def execute(self, warehouse_path: Path) -> ContractCheckResult:
        """Read the current schema and return the semver-relevant differences."""
        current = self._store.read_schema(warehouse_path, base=self._contract)
        diff = diff_contracts(self._contract, current)
        return ContractCheckResult(
            committed_version=self._contract.contract_version,
            current_table_names=tuple(table.name for table in current.tables),
            diff=diff,
        )


def table_specs(contract: ArtifactContract, manifest: Mapping[str, Any]) -> dict[str, TableSpec]:
    """Join the contract with dbt column descriptions from the manifest."""
    nodes = manifest.get("nodes")
    if not isinstance(nodes, dict):
        raise ConfigError("dbt manifest has no nodes; run lakehouse build first")
    by_name = {
        str(node.get("name")): node
        for node in nodes.values()
        if isinstance(node, dict) and node.get("resource_type") == "model"
    }
    specs: dict[str, TableSpec] = {}
    for table in contract.tables:
        node = by_name.get(table.name)
        if node is None:
            raise ConfigError(f"dbt manifest does not contain model {table.name!r}")
        columns = node.get("columns")
        if not isinstance(columns, dict):
            raise ConfigError(f"dbt model {table.name!r} has no documented columns")
        descriptions: dict[str, str] = {}
        for column in table.columns:
            entry = columns.get(column.name)
            description = str(entry.get("description", "")) if isinstance(entry, dict) else ""
            if not description.strip():
                raise ConfigError(
                    f"dbt model {table.name!r} has no description for column {column.name!r}"
                )
            descriptions[column.name] = description.strip()
        specs[table.name] = TableSpec(
            kind=table.kind,
            grain=table.grain,
            descriptions=descriptions,
        )
    return specs


def _request(  # noqa: PLR0913 - explicit request assembly
    warehouse_path: Path,
    out_dir: Path,
    contract: ArtifactContract,
    specs: Mapping[str, TableSpec],
    *,
    built_from: tuple[SourceRef, ...],
    generator: str,
    data_mode: str,
    attribution: str,
    quality: QualityCounts,
) -> PublishRequest:
    return PublishRequest(
        source_warehouse=warehouse_path,
        out_dir=out_dir,
        contract=contract,
        table_specs=specs,
        generator=generator,
        duckdb_version=_package_version("duckdb"),
        dbt_core_version=_package_version("dbt-core"),
        data_mode=data_mode,
        built_from=built_from,
        quality=quality,
        attribution=attribution,
    )


def _package_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError as exc:
        raise ConfigError(f"package {distribution!r} is not installed") from exc
