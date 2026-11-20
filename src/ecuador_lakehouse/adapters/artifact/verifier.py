"""Artifact verifier implementing the ``ArtifactStore`` port (S14).

Verification is intentionally redundant: ``SHA256SUMS`` protects the bytes, the
manifest protects the public schema and row counts, the logical
``content_sha256`` protects the data inside the DuckDB file, and the Parquet
files are cross-checked against the manifest. Any mismatch raises
:class:`ArtifactVerificationError`, which the CLI maps to exit code 8.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from ecuador_lakehouse.adapters.artifact.fingerprint import (
    content_sha256,
    file_sha256,
    quote_identifier,
    quote_literal,
    read_schema,
)
from ecuador_lakehouse.application.ports import VerifyResult
from ecuador_lakehouse.domain.contract import ArtifactContract
from ecuador_lakehouse.domain.errors import ArtifactVerificationError
from ecuador_lakehouse.domain.manifest import ArtifactManifest, TableInfo

_DATABASE_NAME = "ecuador_lakehouse.duckdb"
_FORBIDDEN_SCHEMAS = frozenset({"raw", "staging", "intermediate"})
_SHA_LENGTH = 64
_CHECKSUM_FIELDS = 2


class DuckDbArtifactVerifier:
    """Re-check every integrity guarantee of a published artifact."""

    def verify(self, artifact_dir: Path) -> VerifyResult:
        """Verify checksums, schemas, row counts and logical content fingerprints."""
        artifact_dir = Path(artifact_dir)
        if not artifact_dir.is_dir():
            raise ArtifactVerificationError(f"artifact directory does not exist: {artifact_dir}")
        manifest = _load_manifest(artifact_dir)
        database_path = artifact_dir / _DATABASE_NAME
        expected_files = _expected_files(artifact_dir, manifest)
        _verify_checksums(artifact_dir, expected_files)
        _verify_parquet_files(artifact_dir, manifest)
        with duckdb.connect(str(database_path), read_only=True) as connection:
            _verify_schemas(connection)
            _verify_tables(connection, manifest)
        return VerifyResult(
            artifact_dir=artifact_dir,
            table_count=len(manifest.tables),
            artifact_version=manifest.artifact_version,
        )

    def read_schema(self, warehouse_path: Path, *, base: ArtifactContract) -> ArtifactContract:
        """Read the warehouse marts schema through a read-only connection."""
        with duckdb.connect(str(warehouse_path), read_only=True) as connection:
            return read_schema(connection, base=base)


def _load_manifest(artifact_dir: Path) -> ArtifactManifest:
    path = artifact_dir / "manifest.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ArtifactVerificationError(f"artifact manifest is missing: {path}") from exc
    except OSError as exc:
        raise ArtifactVerificationError(f"artifact manifest is unreadable: {exc}") from exc
    return ArtifactManifest.from_json_text(text)


def _expected_files(artifact_dir: Path, manifest: ArtifactManifest) -> set[str]:
    expected = {"manifest.json", _DATABASE_NAME, "ATTRIBUTION.md"}
    expected.update(table.parquet_file for table in manifest.tables)
    for relative in expected:
        if not (artifact_dir / relative).is_file():
            raise ArtifactVerificationError(f"artifact file is missing: {relative}")
    return expected


def _verify_checksums(artifact_dir: Path, expected_files: set[str]) -> None:
    sums_path = artifact_dir / "SHA256SUMS"
    try:
        lines = sums_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ArtifactVerificationError("SHA256SUMS is missing") from exc
    except OSError as exc:
        raise ArtifactVerificationError(f"SHA256SUMS is unreadable: {exc}") from exc
    recorded: dict[str, str] = {}
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != _CHECKSUM_FIELDS or len(parts[0]) != _SHA_LENGTH:
            raise ArtifactVerificationError(f"SHA256SUMS line {line_number} is malformed: {line!r}")
        digest, relative = parts
        _require_safe_path(relative)
        if relative in recorded:
            raise ArtifactVerificationError(f"SHA256SUMS lists {relative!r} twice")
        recorded[relative] = digest.lower()
    missing = expected_files - set(recorded)
    if missing:
        raise ArtifactVerificationError(f"SHA256SUMS does not cover: {', '.join(sorted(missing))}")
    for relative in sorted(recorded):
        actual = file_sha256(artifact_dir / relative)
        if actual != recorded[relative]:
            raise ArtifactVerificationError(
                f"SHA-256 mismatch for {relative}: manifest checksum does not match the bytes"
            )
    for path in sorted(artifact_dir.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            relative = path.relative_to(artifact_dir).as_posix()
            if relative not in recorded:
                raise ArtifactVerificationError(f"artifact contains an unlisted file: {relative}")


def _require_safe_path(relative: str) -> None:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ArtifactVerificationError(f"SHA256SUMS contains an unsafe path: {relative!r}")


def _verify_parquet_files(artifact_dir: Path, manifest: ArtifactManifest) -> None:
    table_names = {table.name for table in manifest.tables}
    found = {path.stem for path in (artifact_dir / "parquet").glob("*.parquet")}
    missing = table_names - found
    if missing:
        raise ArtifactVerificationError(
            f"parquet files are missing for: {', '.join(sorted(missing))}"
        )
    with duckdb.connect() as connection:
        for table in manifest.tables:
            _verify_parquet(connection, artifact_dir, table)


def _verify_parquet(
    connection: duckdb.DuckDBPyConnection, artifact_dir: Path, table: TableInfo
) -> None:
    path = quote_literal(str(artifact_dir / table.parquet_file))
    rows = connection.execute(
        f"SELECT count(*) FROM read_parquet({path})"  # noqa: S608 - quoted path
    ).fetchone()
    if rows is None or int(rows[0]) != table.row_count:
        actual = int(rows[0]) if rows is not None else 0
        raise ArtifactVerificationError(
            f"parquet row count mismatch for {table.name}: "
            f"manifest says {table.row_count}, file has {actual}"
        )
    columns = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet({path})"  # noqa: S608 - quoted path
    ).fetchall()
    actual_columns = [(str(row[0]), str(row[1])) for row in columns]
    expected_columns = [(column.name, column.type) for column in table.columns]
    if actual_columns != expected_columns:
        raise ArtifactVerificationError(
            f"parquet schema mismatch for {table.name}: manifest says {expected_columns}, "
            f"file has {actual_columns}"
        )


def _verify_schemas(connection: duckdb.DuckDBPyConnection) -> None:
    schemas = {
        str(row[0])
        for row in connection.execute(
            "SELECT schema_name FROM information_schema.schemata"
        ).fetchall()
    }
    forbidden = schemas & _FORBIDDEN_SCHEMAS
    if forbidden:
        raise ArtifactVerificationError(
            f"artifact DuckDB file exposes non-marts schemas: {', '.join(sorted(forbidden))}"
        )
    if "marts" not in schemas:
        raise ArtifactVerificationError("artifact DuckDB file has no marts schema")


def _verify_tables(connection: duckdb.DuckDBPyConnection, manifest: ArtifactManifest) -> None:
    actual = {
        str(row[0])
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'marts'"
        ).fetchall()
    }
    expected = {table.name for table in manifest.tables}
    missing = expected - actual
    if missing:
        raise ArtifactVerificationError(
            f"artifact database is missing tables: {', '.join(sorted(missing))}"
        )
    extra = actual - expected
    if extra:
        raise ArtifactVerificationError(
            f"artifact database has uncontracted tables: {', '.join(sorted(extra))}"
        )
    for table in manifest.tables:
        _verify_table(connection, table)


def _verify_table(connection: duckdb.DuckDBPyConnection, table: TableInfo) -> None:
    identifier = quote_identifier(table.name)
    rows = connection.execute(
        f"SELECT count(*) FROM marts.{identifier}"  # noqa: S608 - validated identifier
    ).fetchone()
    if rows is None or int(rows[0]) != table.row_count:
        raise ArtifactVerificationError(
            f"row count mismatch for {table.name}: manifest says {table.row_count}"
        )
    columns = connection.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'marts' AND table_name = ? ORDER BY ordinal_position",
        [table.name],
    ).fetchall()
    actual_columns = [(str(row[0]), str(row[1])) for row in columns]
    expected_columns = [(column.name, column.type) for column in table.columns]
    if actual_columns != expected_columns:
        raise ArtifactVerificationError(
            f"schema mismatch for {table.name}: manifest says {expected_columns}, "
            f"database has {actual_columns}"
        )
    actual_content = content_sha256(connection, table.name)
    if actual_content != table.content_sha256:
        raise ArtifactVerificationError(
            f"content fingerprint mismatch for {table.name}: the data was modified"
        )
