"""Content fingerprints and schema inspection shared by the artifact adapters.

The determinism guarantee (S15) is defined on *logical* table content, not on
DuckDB or Parquet bytes: two builds must produce the same
``sha256(COPY (SELECT * FROM t ORDER BY ALL) TO ... (FORMAT CSV))``. This module
owns that fingerprint, plain file hashing and the ``information_schema`` query
used by publishing and contract checks.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

import duckdb

from ecuador_lakehouse.domain.contract import ArtifactContract, ContractColumn, ContractTable

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CHUNK = 1024 * 1024


def quote_identifier(name: str) -> str:
    """Return a validated, double-quoted SQL identifier."""
    if _IDENTIFIER.fullmatch(name) is None:
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return f'"{name}"'


def quote_literal(value: str) -> str:
    """Return a single-quoted SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def file_sha256(path: Path) -> str:
    """Return the SHA-256 of a file, read in constant memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def content_sha256(connection: duckdb.DuckDBPyConnection, table: str) -> str:
    """Hash the logical content of ``marts.<table>`` in a row-order-independent way."""
    qualified = f"marts.{quote_identifier(table)}"
    with tempfile.TemporaryDirectory(prefix="lakehouse-content-") as directory:
        target = Path(directory) / "content.csv"
        connection.execute(
            f"COPY (SELECT * FROM {qualified} ORDER BY ALL) "  # noqa: S608 - validated identifier
            f"TO {quote_literal(str(target))} (FORMAT CSV)"
        )
        return file_sha256(target)


def read_schema(
    connection: duckdb.DuckDBPyConnection, *, base: ArtifactContract
) -> ArtifactContract:
    """Read the materialized ``marts`` schema and merge it with ``base`` metadata."""
    tables = [
        str(row[0])
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'marts' ORDER BY table_name"
        ).fetchall()
    ]
    contract_tables: list[ContractTable] = []
    for name in tables:
        rows = connection.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'marts' AND table_name = ? ORDER BY ordinal_position",
            [name],
        ).fetchall()
        columns = tuple(ContractColumn(name=str(row[0]), type=str(row[1])) for row in rows)
        known = base.find_table(name)
        kind = known.kind if known is not None else _infer_kind(name)
        grain = known.grain if known is not None else "unknown"
        contract_tables.append(ContractTable(name=name, kind=kind, grain=grain, columns=columns))
    return ArtifactContract(
        contract_version=base.contract_version,
        artifact_name=base.artifact_name,
        tables=tuple(contract_tables),
    )


def _infer_kind(name: str) -> str:
    if name.startswith("dim_"):
        return "dim"
    if name.startswith("fct_"):
        return "fct"
    return "mart"
