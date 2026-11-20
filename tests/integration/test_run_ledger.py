"""Integration tests for the ``meta.runs`` ledger and warehouse reopen semantics."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ecuador_lakehouse.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from ecuador_lakehouse.domain.runs import RunRecord, RunStatus, StepResult, StepStatus


def _record(run_id: str, status: RunStatus = RunStatus.OK) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        started_at=datetime(2026, 11, 20, 10, 0, 0),
        finished_at=datetime(2026, 11, 20, 10, 0, 9, tzinfo=UTC).replace(tzinfo=None),
        status=status,
        mode="sample",
        steps=(
            StepResult(
                "load_raw",
                StepStatus.OK,
                duration_s=1.5,
                detail="12 partitions",
                metrics={"loaded": 12, "skipped": 0, "replaced": 0},
            ),
        ),
    )


def test_runs_are_appended_and_read_back_with_their_metrics(tmp_path: Path) -> None:
    warehouse = DuckDbWarehouse(tmp_path / "warehouse.duckdb")
    try:
        warehouse.record_run(_record("run-a"))
        warehouse.record_run(_record("run-b", RunStatus.FAILED))

        runs = warehouse.runs()
        assert [run.run_id for run in runs] == ["run-a", "run-b"]
        assert runs[1].status is RunStatus.FAILED
        assert runs[0].steps[0].metrics == {"loaded": 12, "skipped": 0, "replaced": 0}
        assert runs[0].steps[0].detail == "12 partitions"
    finally:
        warehouse.close()


def test_open_reopens_the_file_after_close(tmp_path: Path) -> None:
    path = tmp_path / "warehouse.duckdb"
    warehouse = DuckDbWarehouse(path)
    warehouse.record_run(_record("run-before-close"))
    warehouse.close()
    warehouse.close()

    warehouse.open()
    warehouse.open()
    try:
        assert [run.run_id for run in warehouse.runs()] == ["run-before-close"]
        assert warehouse.path == path
        assert warehouse.ledger() == ()
    finally:
        warehouse.close()


def test_open_is_idempotent_on_a_fresh_warehouse(tmp_path: Path) -> None:
    warehouse = DuckDbWarehouse(tmp_path / "warehouse.duckdb")
    try:
        warehouse.open()
        assert warehouse.runs() == ()
    finally:
        warehouse.close()
