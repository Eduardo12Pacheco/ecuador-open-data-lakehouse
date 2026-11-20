"""DuckDB adapter implementing the ``Warehouse`` port (S6, D3, D5).

One partition load is one transaction (unit of work): the previous rows of the
partition are deleted, the canonical CSV is bulk-loaded through
``read_csv(all_varchar=true)`` and the batch ledger is updated. An identical
current vintage is a no-op. Any failure rolls the whole partition back.
"""

from __future__ import annotations

import contextlib
import csv
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from ecuador_lakehouse.adapters.warehouse.ddl import RAW_SCHEMA, RAW_TABLES, RawTable, schema_ddl
from ecuador_lakehouse.application.ports import LoadResult
from ecuador_lakehouse.domain.batches import BatchRecord, BatchStatus, make_batch_id
from ecuador_lakehouse.domain.errors import LakehouseError, SourceSchemaError
from ecuador_lakehouse.domain.runs import RunRecord, RunStatus, StepResult, StepStatus
from ecuador_lakehouse.domain.sources import SourceId

_READ_CSV = "read_csv(?, header = true, all_varchar = true, nullstr = ['\\N'])"
_BATCH_COLUMNS = (
    "batch_id",
    "source_id",
    "partition_key",
    "source_sha256",
    "row_count",
    "status",
    "mode",
    "loaded_at",
    "is_current",
)
_SELECT_BATCH = (
    "SELECT batch_id, source_id, partition_key, source_sha256, row_count, "
    "status, mode, loaded_at, is_current FROM meta.batches"
)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class DuckDbWarehouse:
    """Single-file DuckDB warehouse with an append-only batch ledger."""

    def __init__(
        self,
        path: Path,
        *,
        mode: str = "sample",
        clock: Callable[[], datetime] | None = None,
        connection: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        if not mode.strip():
            raise ValueError("mode must not be empty")
        self._path = path
        self._mode = mode
        self._clock = clock if clock is not None else _utc_now
        if connection is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = duckdb.connect(str(path))
        self._connection: duckdb.DuckDBPyConnection | None = connection
        try:
            self._ensure_schema(connection)
        except BaseException:
            self.close()
            raise

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Return the live DuckDB connection (read-only use by tests and docs)."""
        connection = self._connection
        if connection is None:
            raise LakehouseError("warehouse is closed")
        return connection

    @property
    def path(self) -> Path:
        """Return the database file path."""
        return self._path

    def load_partition(
        self,
        source_id: SourceId,
        partition: str,
        canonical_csv: Path,
        sha256: str,
        source_file: str,
    ) -> LoadResult:
        """Load ``canonical_csv`` as one unit of work and return the ledger outcome."""
        if not source_file.strip():
            raise ValueError("source_file must not be empty")
        table = RAW_TABLES.get(source_id)
        if table is None:
            raise SourceSchemaError(f"no raw table is defined for source {source_id.value!r}")
        batch_id = make_batch_id(source_id, partition, sha256)
        connection = self.connection
        connection.execute("BEGIN TRANSACTION")
        try:
            current = self._current_batch(source_id, partition)
            if current is not None and current.source_sha256 == sha256:
                connection.execute("ROLLBACK")
                return LoadResult(
                    source_id=source_id,
                    partition=partition,
                    batch_id=current.batch_id,
                    status=BatchStatus.SKIPPED,
                    row_count=current.row_count,
                )
            replaced = self._has_batches(source_id, partition)
            self._delete_partition(connection, table, source_id, partition)
            connection.execute(
                "UPDATE meta.batches SET is_current = false "
                "WHERE source_id = ? AND partition_key = ? AND is_current",
                [source_id.value, partition],
            )
            connection.execute("DELETE FROM meta.batches WHERE batch_id = ?", [batch_id])
            row_count = self._validate_csv(canonical_csv, table)
            connection.execute(
                f"INSERT INTO {RAW_SCHEMA}.{table.name} "  # noqa: S608 - frozen table name
                f"SELECT *, ?, ?, ? FROM {_READ_CSV}",
                [batch_id, source_file, sha256, str(canonical_csv)],
            )
            loaded_rows = connection.execute(
                f"SELECT count(*) FROM {RAW_SCHEMA}.{table.name} "  # noqa: S608
                "WHERE _batch_id = ?",
                [batch_id],
            ).fetchone()
            if loaded_rows is None or loaded_rows[0] != row_count:
                raise SourceSchemaError(
                    f"canonical CSV {canonical_csv.name!r} loaded "
                    f"{loaded_rows[0] if loaded_rows else 0} rows, expected {row_count}"
                )
            status = BatchStatus.REPLACED if replaced else BatchStatus.LOADED
            connection.execute(
                "INSERT INTO meta.batches "  # noqa: S608 - constant column list
                f"({', '.join(_BATCH_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    batch_id,
                    source_id.value,
                    partition,
                    sha256,
                    row_count,
                    status.value,
                    self._mode,
                    self._clock(),
                    True,
                ],
            )
            connection.execute("COMMIT")
        except LakehouseError:
            self._rollback(connection)
            raise
        except duckdb.Error as error:
            self._rollback(connection)
            raise LakehouseError(
                f"warehouse load failed for {source_id.value}/{partition}: {error}"
            ) from error
        except BaseException:
            self._rollback(connection)
            raise
        return LoadResult(
            source_id=source_id,
            partition=partition,
            batch_id=batch_id,
            status=status,
            row_count=row_count,
        )

    def ledger(self) -> tuple[BatchRecord, ...]:
        """Return every batch row, oldest first (history is never deleted)."""
        rows = self.connection.execute(
            f"{_SELECT_BATCH} ORDER BY loaded_at, source_id, partition_key, batch_id"
        ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    def record_run(self, record: RunRecord) -> None:
        """Insert one completed run into ``meta.runs``."""
        self.connection.execute(
            "INSERT INTO meta.runs "
            "(run_id, started_at, finished_at, status, mode, steps_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                record.run_id,
                record.started_at,
                record.finished_at,
                record.status.value,
                record.mode,
                record.steps_json(),
            ],
        )

    def runs(self) -> tuple[RunRecord, ...]:
        """Return every recorded run, oldest first."""
        rows = self.connection.execute(
            "SELECT run_id, started_at, finished_at, status, mode, steps_json "
            "FROM meta.runs ORDER BY started_at, run_id"
        ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

    def open(self) -> None:
        """Open the database file again after dbt had exclusive access (D18)."""
        if self._connection is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(str(self._path))
        try:
            self._ensure_schema(connection)
        except BaseException:
            connection.close()
            raise
        self._connection = connection

    def close(self) -> None:
        """Release the file lock (safe to call twice and on Windows)."""
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.close()

    def __enter__(self) -> DuckDbWarehouse:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @staticmethod
    def _ensure_schema(connection: duckdb.DuckDBPyConnection) -> None:
        for statement in schema_ddl():
            connection.execute(statement)

    def _current_batch(self, source_id: SourceId, partition: str) -> BatchRecord | None:
        row = self.connection.execute(
            f"{_SELECT_BATCH} WHERE source_id = ? AND partition_key = ? AND is_current "
            "ORDER BY loaded_at DESC LIMIT 1",
            [source_id.value, partition],
        ).fetchone()
        return None if row is None else self._record_from_row(row)

    @staticmethod
    def _record_from_row(row: tuple[object, ...]) -> BatchRecord:
        return BatchRecord(
            batch_id=str(row[0]),
            source_id=SourceId(str(row[1])),
            partition=str(row[2]),
            source_sha256=str(row[3]),
            row_count=int(str(row[4])),
            status=BatchStatus(str(row[5])),
            mode=str(row[6]),
            loaded_at=row[7],  # type: ignore[arg-type]
            is_current=bool(row[8]),
        )

    @staticmethod
    def _run_from_row(row: tuple[object, ...]) -> RunRecord:
        raw_steps = json.loads(str(row[5]))
        steps = tuple(
            StepResult(
                name=str(step["name"]),
                status=StepStatus(str(step["status"])),
                duration_s=float(step["duration_s"]),
                detail=str(step.get("detail", "")),
                metrics={str(key): int(value) for key, value in step.get("metrics", {}).items()},
                attempts=int(step.get("attempts", 1)),
            )
            for step in raw_steps
        )
        return RunRecord(
            run_id=str(row[0]),
            started_at=row[1],  # type: ignore[arg-type]
            finished_at=row[2],  # type: ignore[arg-type]
            status=RunStatus(str(row[3])),
            mode=str(row[4]),
            steps=steps,
        )

    def _has_batches(self, source_id: SourceId, partition: str) -> bool:
        row = self.connection.execute(
            "SELECT count(*) FROM meta.batches WHERE source_id = ? AND partition_key = ?",
            [source_id.value, partition],
        ).fetchone()
        return bool(row is not None and row[0] > 0)

    def _delete_partition(
        self,
        connection: duckdb.DuckDBPyConnection,
        table: RawTable,
        source_id: SourceId,
        partition: str,
    ) -> None:
        connection.execute(
            f"DELETE FROM {RAW_SCHEMA}.{table.name} "  # noqa: S608 - frozen table name
            "WHERE _batch_id IN ("
            "SELECT batch_id FROM meta.batches WHERE source_id = ? AND partition_key = ?)",
            [source_id.value, partition],
        )

    @staticmethod
    def _validate_csv(canonical_csv: Path, table: RawTable) -> int:
        """Check header, field width and count before DuckDB reads the file."""
        try:
            handle = canonical_csv.open("r", encoding="utf-8", newline="")
        except OSError as error:
            raise SourceSchemaError(
                f"canonical CSV for {table.name!r} is unreadable: {canonical_csv.name!r}"
            ) from error
        with handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None:
                raise SourceSchemaError(f"canonical CSV {canonical_csv.name!r} is empty")
            if tuple(header) != table.columns:
                raise SourceSchemaError(
                    f"canonical CSV {canonical_csv.name!r} header does not match "
                    f"raw.{table.name}: expected {', '.join(table.columns)}"
                )
            width = len(table.columns)
            count = 0
            for line_number, line in enumerate(reader, start=2):
                if len(line) != width:
                    raise SourceSchemaError(
                        f"canonical CSV {canonical_csv.name!r} line {line_number} has "
                        f"{len(line)} fields but the header has {width}"
                    )
                count += 1
        return count

    @staticmethod
    def _rollback(connection: duckdb.DuckDBPyConnection) -> None:
        with contextlib.suppress(duckdb.Error):
            connection.execute("ROLLBACK")
