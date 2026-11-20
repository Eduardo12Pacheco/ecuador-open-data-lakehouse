"""Tests for the pipeline run-ledger value objects."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ecuador_lakehouse.domain.runs import RunRecord, RunStatus, StepResult, StepStatus

START = datetime(2026, 11, 20, 10, 0, 0)
END = datetime(2026, 11, 20, 10, 0, 5)


def test_step_result_round_trips_through_json() -> None:
    result = StepResult(
        name="load_raw",
        status=StepStatus.OK,
        duration_s=1.23456,
        detail="12 partitions",
        metrics={"loaded": 12, "skipped": 0, "replaced": 0},
    )

    payload = result.to_json()

    assert payload == {
        "name": "load_raw",
        "status": "ok",
        "duration_s": 1.235,
        "detail": "12 partitions",
        "metrics": {"loaded": 12, "replaced": 0, "skipped": 0},
        "attempts": 1,
    }


def test_run_record_serialises_steps_as_deterministic_json() -> None:
    record = RunRecord(
        run_id="run-1",
        started_at=START,
        finished_at=END,
        status=RunStatus.OK,
        mode="sample",
        steps=(
            StepResult("acquire", StepStatus.OK, 0.2, metrics={"fetched": 12}),
            StepResult("load_raw", StepStatus.OK, 0.4, metrics={"loaded": 12}),
        ),
    )

    assert record.duration_s == 5.0
    assert record.ok is True
    assert record.steps_json() == (
        '[{"attempts":1,"detail":"","duration_s":0.2,"metrics":{"fetched":12},'
        '"name":"acquire","status":"ok"},'
        '{"attempts":1,"detail":"","duration_s":0.4,"metrics":{"loaded":12},'
        '"name":"load_raw","status":"ok"}]'
    )


def test_failed_run_is_not_ok() -> None:
    record = RunRecord(
        run_id="run-2",
        started_at=START,
        finished_at=END,
        status=RunStatus.FAILED,
        mode="sample",
    )

    assert record.ok is False
    assert record.steps == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"run_id": "", "mode": "sample"},
        {"run_id": "run", "mode": ""},
        {"run_id": "run", "mode": "sample", "finished_at": START.replace(hour=9)},
    ],
)
def test_run_record_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "run_id": "run",
        "started_at": START,
        "finished_at": END,
        "status": RunStatus.OK,
        "mode": "sample",
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match="must"):
        RunRecord(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"name": ""},
        {"name": "step", "duration_s": -1.0},
        {"name": "step", "attempts": 0},
        {"name": "step", "metrics": {"loaded": -1}},
        {"name": "step", "metrics": {"": 1}},
        {"name": "step", "metrics": {"loaded": True}},
        {"name": "step", "metrics": {"loaded": 1.5}},
    ],
)
def test_step_result_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "name": "step",
        "status": StepStatus.OK,
        "duration_s": 0.1,
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match="must"):
        StepResult(**values)  # type: ignore[arg-type]


def test_utc_naive_timestamps_are_accepted() -> None:
    record = RunRecord(
        run_id="run-3",
        started_at=datetime.now(UTC).replace(tzinfo=None),
        finished_at=datetime.now(UTC).replace(tzinfo=None),
        status=RunStatus.OK,
        mode="full",
    )

    assert record.mode == "full"
