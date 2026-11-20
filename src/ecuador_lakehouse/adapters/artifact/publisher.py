"""DuckDB artifact publisher implementing the ``ArtifactStore`` port (S14, D19).

The published directory is self-describing and verifiable:

    ecuador-lakehouse-<artifact_version>/
        ecuador_lakehouse.duckdb   # only marts + meta schemas
        parquet/<table>.parquet    # ZSTD, one file per published table
        manifest.json              # deterministic, no wall-clock fields
        SHA256SUMS                 # every payload file
        ATTRIBUTION.md

Parquet and DuckDB file bytes are not reproducible, so the manifest carries a
logical ``content_sha256`` per table computed from a canonical CSV export.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from ecuador_lakehouse.adapters.artifact.fingerprint import (
    content_sha256,
    file_sha256,
    quote_identifier,
    quote_literal,
    read_schema,
)
from ecuador_lakehouse.adapters.artifact.verifier import DuckDbArtifactVerifier
from ecuador_lakehouse.application.ports import (
    PublishRequest,
    PublishResult,
    TableSpec,
    VerifyResult,
)
from ecuador_lakehouse.domain.contract import ArtifactContract, ContractColumn, ContractTable
from ecuador_lakehouse.domain.errors import ArtifactVerificationError
from ecuador_lakehouse.domain.manifest import ArtifactManifest, ColumnInfo, TableInfo


class DuckDbArtifactPublisher:
    """Materialize a warehouse's marts as a versioned, self-verifying artifact."""

    def publish(self, request: PublishRequest) -> PublishResult:
        """Write the full artifact tree and return its directory and manifest."""
        contract = request.contract
        artifact_dir = request.out_dir / f"{contract.artifact_name}-{contract.contract_version}"
        if request.source_warehouse.resolve() == artifact_dir.resolve():
            raise ArtifactVerificationError("artifact directory must differ from the warehouse")
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        parquet_dir = artifact_dir / "parquet"
        parquet_dir.mkdir(parents=True)
        (artifact_dir / "ATTRIBUTION.md").write_text(request.attribution, encoding="utf-8")
        database_path = artifact_dir / "ecuador_lakehouse.duckdb"

        table_infos = _export_tables(request, database_path, parquet_dir)
        _record_build_info(database_path, request)

        manifest = ArtifactManifest(
            artifact_name=contract.artifact_name,
            artifact_version=contract.contract_version,
            generator=request.generator,
            duckdb_version=request.duckdb_version,
            dbt_core_version=request.dbt_core_version,
            data_mode=request.data_mode,
            built_from=request.built_from,
            tables=tuple(table_infos),
            quality=request.quality,
            attribution=request.attribution,
        )
        manifest_path = artifact_dir / "manifest.json"
        manifest_path.write_text(manifest.to_json_text(), encoding="utf-8")
        _write_checksums(artifact_dir)
        return PublishResult(artifact_dir=artifact_dir, manifest=manifest)

    def verify(self, artifact_dir: Path) -> VerifyResult:
        """Delegate verification to the dedicated verifier adapter."""
        return DuckDbArtifactVerifier().verify(artifact_dir)

    def read_schema(self, warehouse_path: Path, *, base: ArtifactContract) -> ArtifactContract:
        """Read the warehouse marts schema through a read-only connection."""
        with duckdb.connect(str(warehouse_path), read_only=True) as connection:
            return read_schema(connection, base=base)


def _export_tables(
    request: PublishRequest, database_path: Path, parquet_dir: Path
) -> list[TableInfo]:
    contract = request.contract
    expected = {table.name: table for table in contract.tables}
    infos: list[TableInfo] = []
    with duckdb.connect(str(request.source_warehouse)) as connection:
        actual = read_schema(connection, base=contract)
        _require_matching_schema(contract, actual)
        connection.execute(f"ATTACH DATABASE {quote_literal(str(database_path))} AS artifact")
        try:
            connection.execute("CREATE SCHEMA artifact.marts")
            connection.execute("CREATE SCHEMA artifact.meta")
            for name in sorted(expected):
                identifier = quote_identifier(name)
                table = expected[name]
                spec = request.table_specs[name]
                columns = _columns(connection, name)
                row_count = _row_count(connection, name)
                content_sha = content_sha256(connection, name)
                parquet_file = f"parquet/{name}.parquet"
                connection.execute(
                    f"COPY (SELECT * FROM marts.{identifier} ORDER BY ALL) "  # noqa: S608
                    f"TO {quote_literal(str(parquet_dir / f'{name}.parquet'))} "
                    "(FORMAT PARQUET, COMPRESSION ZSTD)"
                )
                connection.execute(
                    f"CREATE TABLE artifact.marts.{identifier} AS SELECT * FROM marts.{identifier}"  # noqa: S608 - validated identifier
                )
                infos.append(
                    TableInfo(
                        name=name,
                        kind=spec.kind,
                        grain=spec.grain,
                        row_count=row_count,
                        columns=_describe_columns(table, columns, spec),
                        content_sha256=content_sha,
                        parquet_file=parquet_file,
                    )
                )
        finally:
            connection.execute("DETACH artifact")
    return infos


def _require_matching_schema(contract: ArtifactContract, actual: ArtifactContract) -> None:
    expected = {table.name: table for table in contract.tables}
    found = {table.name: table for table in actual.tables}
    if set(expected) != set(found):
        missing = sorted(set(expected) - set(found))
        extra = sorted(set(found) - set(expected))
        details = []
        if missing:
            details.append(f"missing tables: {', '.join(missing)}")
        if extra:
            details.append(f"uncontracted tables: {', '.join(extra)}")
        raise ArtifactVerificationError(
            "warehouse schema does not match the artifact contract ("
            + "; ".join(details)
            + "); run lakehouse contract check"
        )
    for name, table in expected.items():
        committed = {column.name: column.type for column in table.columns}
        materialized = {column.name: column.type for column in found[name].columns}
        if committed != materialized:
            raise ArtifactVerificationError(
                f"warehouse table {name!r} does not match the artifact contract; "
                "run lakehouse contract check"
            )


def _describe_columns(
    table: ContractTable, columns: tuple[ContractColumn, ...], spec: TableSpec
) -> tuple[ColumnInfo, ...]:
    descriptions: list[ColumnInfo] = []
    for column in columns:
        description = spec.descriptions.get(column.name, "").strip()
        if not description:
            raise ArtifactVerificationError(
                f"column {table.name}.{column.name} has no dbt description"
            )
        descriptions.append(ColumnInfo(name=column.name, type=column.type, description=description))
    return tuple(descriptions)


def _columns(connection: duckdb.DuckDBPyConnection, name: str) -> tuple[ContractColumn, ...]:
    rows = connection.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'marts' AND table_name = ? ORDER BY ordinal_position",
        [name],
    ).fetchall()
    return tuple(ContractColumn(name=str(row[0]), type=str(row[1])) for row in rows)


def _row_count(connection: duckdb.DuckDBPyConnection, name: str) -> int:
    row = connection.execute(
        f"SELECT count(*) FROM marts.{quote_identifier(name)}"  # noqa: S608 - validated identifier
    ).fetchone()
    return int(row[0]) if row is not None else 0


def _record_build_info(database_path: Path, request: PublishRequest) -> None:
    with duckdb.connect(str(database_path)) as connection:
        connection.execute(
            "CREATE TABLE meta.build_info ("
            "built_at TIMESTAMP NOT NULL, "
            "artifact_version VARCHAR NOT NULL, "
            "generator VARCHAR NOT NULL, "
            "data_mode VARCHAR NOT NULL)"
        )
        connection.execute(
            "INSERT INTO meta.build_info VALUES (?, ?, ?, ?)",
            [
                datetime.now(UTC).replace(tzinfo=None),
                str(request.contract.contract_version),
                request.generator,
                request.data_mode,
            ],
        )


def _write_checksums(artifact_dir: Path) -> None:
    entries: list[tuple[str, str]] = []
    for path in sorted(artifact_dir.rglob("*")):
        if not path.is_file() or path.name == "SHA256SUMS":
            continue
        entries.append((file_sha256(path), path.relative_to(artifact_dir).as_posix()))
    lines = "\n".join(f"{digest}  {name}" for digest, name in sorted(entries, key=lambda e: e[1]))
    (artifact_dir / "SHA256SUMS").write_text(lines + "\n", encoding="utf-8")
