"""Value objects for the run ledger written to ``meta.runs`` (S13).

A run is one invocation of the pipeline. Each executed step records its status,
wall-clock duration, attempt count, a human-readable detail and numeric metrics
(for example ``loaded``/``skipped``/``replaced`` partitions or passed tests).
The ledger stores the step results as compact JSON so a later ``doctor`` or
report can explain what happened without re-reading logs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RunStatus(StrEnum):
    """Final status of one pipeline run."""

    OK = "ok"
    FAILED = "failed"


class StepStatus(StrEnum):
    """Final status of one pipeline step."""

    OK = "ok"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StepResult:
    """Outcome of one executed pipeline step."""

    name: str
    status: StepStatus
    duration_s: float
    detail: str = ""
    metrics: Mapping[str, int] = field(default_factory=dict)
    attempts: int = 1

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("step result name must not be empty")
        if self.duration_s < 0:
            raise ValueError(f"duration_s must be non-negative: {self.duration_s!r}")
        if self.attempts < 1:
            raise ValueError(f"attempts must be at least 1: {self.attempts!r}")
        for key, value in self.metrics.items():
            if not key.strip():
                raise ValueError("metric names must not be empty")
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"metric {key!r} must be an integer: {value!r}")
            if value < 0:
                raise ValueError(f"metric {key!r} must be non-negative: {value!r}")

    @property
    def ok(self) -> bool:
        """Whether the step finished successfully."""
        return self.status is StepStatus.OK

    def to_json(self) -> dict[str, object]:
        """Return a stable JSON-ready representation for the run ledger."""
        return {
            "name": self.name,
            "status": self.status.value,
            "duration_s": round(self.duration_s, 3),
            "detail": self.detail,
            "metrics": dict(sorted(self.metrics.items())),
            "attempts": self.attempts,
        }


@dataclass(frozen=True, slots=True)
class RunRecord:
    """One row of ``meta.runs``: a whole pipeline execution."""

    run_id: str
    started_at: datetime
    finished_at: datetime
    status: RunStatus
    mode: str
    steps: tuple[StepResult, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.mode.strip():
            raise ValueError("mode must not be empty")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not be before started_at")
        object.__setattr__(self, "steps", tuple(self.steps))

    @property
    def ok(self) -> bool:
        """Whether the run finished successfully."""
        return self.status is RunStatus.OK

    @property
    def duration_s(self) -> float:
        """Wall-clock duration of the whole run."""
        return (self.finished_at - self.started_at).total_seconds()

    def steps_json(self) -> str:
        """Serialise every step result as deterministic compact JSON."""
        return json.dumps(
            [step.to_json() for step in self.steps],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
