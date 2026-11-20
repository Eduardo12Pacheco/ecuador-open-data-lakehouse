"""Custom pipeline runner implementing the S13 orchestrator (D6).

The runner owns *what* executes and *in which order*; the actual work lives in
small application use cases wired by the composition root. A ``Dag`` (pure
domain) validates the graph, this module adds execution concerns: selection
modes, retry policies for idempotent steps, stop-on-first-failure and the
``meta.runs`` ledger.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from ecuador_lakehouse.application.ports import RunLedger
from ecuador_lakehouse.domain.dag import Dag
from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.runs import RunRecord, RunStatus, StepResult, StepStatus

_MIN_RETRY_ATTEMPTS = 2

StepExecutor = Callable[["StepContext"], StepResult]


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(slots=True)
class StepContext:
    """Mutable scratch space shared by the steps of one run.

    ``outputs`` carries typed payloads between steps (for example the
    ``FetchResult`` tuple produced by ``acquire`` and consumed by ``load_raw``);
    ``results`` exposes the outcome of every step that already ran.
    """

    run_id: str
    mode: str
    outputs: dict[str, object] = field(default_factory=dict)
    results: dict[str, StepResult] = field(default_factory=dict)

    def output(self, step: str) -> Any:
        """Return the payload published by ``step`` or raise a config error."""
        try:
            return self.outputs[step]
        except KeyError as exc:
            raise ConfigError(
                f"step {step!r} did not run before this step; select its upstream steps too"
            ) from exc


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry settings for one idempotent step."""

    max_attempts: int = 1
    delay_s: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1: {self.max_attempts!r}")
        if self.delay_s < 0:
            raise ValueError(f"delay_s must be non-negative: {self.delay_s!r}")


@dataclass(frozen=True, slots=True)
class RunReport:
    """What the CLI presents after one pipeline invocation."""

    record: RunRecord

    @property
    def status(self) -> RunStatus:
        """Final run status."""
        return self.record.status

    @property
    def ok(self) -> bool:
        """Whether the run finished successfully."""
        return self.record.ok

    @property
    def steps(self) -> tuple[StepResult, ...]:
        """Executed steps in execution order."""
        return self.record.steps

    def metrics(self, step: str) -> Mapping[str, int]:
        """Return the numeric metrics of one executed step."""
        for result in self.record.steps:
            if result.name == step:
                return result.metrics
        raise ConfigError(f"step {step!r} did not run in this invocation")


class PipelineRunner:
    """Execute registered steps over a validated DAG and record the run."""

    def __init__(  # noqa: PLR0913 - explicit composition-root wiring
        self,
        dag: Dag,
        steps: Mapping[str, StepExecutor],
        ledger: RunLedger,
        *,
        mode: str,
        idempotent_steps: frozenset[str] = frozenset(),
        retry_policies: Mapping[str, RetryPolicy] | None = None,
        clock: Callable[[], datetime] | None = None,
        run_id_factory: Callable[[], str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        if not mode.strip():
            raise ValueError("mode must not be empty")
        declared = {step.name for step in dag.steps}
        missing = declared - set(steps)
        unexpected = set(steps) - declared
        if missing:
            raise ConfigError(
                f"no executor registered for pipeline steps: {', '.join(sorted(missing))}"
            )
        if unexpected:
            raise ConfigError(
                f"executors registered for unknown pipeline steps: {', '.join(sorted(unexpected))}"
            )
        policies = dict(retry_policies or {})
        for name, policy in policies.items():
            if name not in declared:
                raise ConfigError(f"retry policy for unknown pipeline step: {name!r}")
            if name not in idempotent_steps:
                raise ConfigError(
                    f"retry policy is only allowed for idempotent steps; {name!r} is not"
                )
            if policy.max_attempts < _MIN_RETRY_ATTEMPTS:
                raise ConfigError(f"retry policy for {name!r} must allow at least 2 attempts")
        self._dag = dag
        self._steps = dict(steps)
        self._ledger = ledger
        self._mode = mode
        self._idempotent = idempotent_steps
        self._policies = policies
        self._clock = clock if clock is not None else _utc_now
        self._run_id_factory = (
            run_id_factory if run_id_factory is not None else (lambda: uuid.uuid4().hex[:16])
        )
        self._sleep = sleep
        self._timer = timer

    @property
    def dag(self) -> Dag:
        """The graph this runner executes."""
        return self._dag

    def run(
        self,
        *,
        select: Sequence[str] | None = None,
        only: str | None = None,
        from_step: str | None = None,
    ) -> RunReport:
        """Execute the selected steps and persist the run in ``meta.runs``."""
        order = self._resolve(select=select, only=only, from_step=from_step)
        run_id = self._run_id_factory()
        if not run_id.strip():
            raise ConfigError("run id factory returned an empty id")
        started_at = self._clock()
        context = StepContext(run_id=run_id, mode=self._mode)
        results: list[StepResult] = []
        for name in order:
            step_started = self._timer()
            try:
                result = self._execute(name, context)
            except Exception as error:
                results.append(
                    StepResult(
                        name=name,
                        status=StepStatus.FAILED,
                        duration_s=self._timer() - step_started,
                        detail=str(error),
                    )
                )
                self._record(
                    run_id=run_id,
                    started_at=started_at,
                    status=RunStatus.FAILED,
                    results=results,
                )
                raise
            results.append(result)
            context.results[name] = result
        return RunReport(
            record=self._record(
                run_id=run_id,
                started_at=started_at,
                status=RunStatus.OK,
                results=results,
            )
        )

    def _execute(self, name: str, context: StepContext) -> StepResult:
        policy = self._policies.get(name, RetryPolicy())
        attempts = 0
        started = self._timer()
        while True:
            attempts += 1
            try:
                result = self._steps[name](context)
            except Exception:
                if attempts < policy.max_attempts:
                    if policy.delay_s:
                        self._sleep(policy.delay_s)
                    continue
                raise
            if not isinstance(result, StepResult):
                raise ConfigError(f"step {name!r} did not return a StepResult")
            duration = self._timer() - started
            return replace(result, name=name, duration_s=duration, attempts=attempts)

    def _record(
        self,
        *,
        run_id: str,
        started_at: datetime,
        status: RunStatus,
        results: Sequence[StepResult],
    ) -> RunRecord:
        record = RunRecord(
            run_id=run_id,
            started_at=started_at,
            finished_at=self._clock(),
            status=status,
            mode=self._mode,
            steps=tuple(results),
        )
        self._ledger.record_run(record)
        return record

    def _resolve(
        self,
        *,
        select: Sequence[str] | None,
        only: str | None,
        from_step: str | None,
    ) -> list[str]:
        modes = sum(1 for mode in (select, only, from_step) if mode is not None)
        if modes > 1:
            raise ConfigError("--select, --only and --from-step are mutually exclusive")
        if only is not None:
            self._dag.get(only)
            return [only]
        if select is not None:
            names = list(select)
            if not names:
                raise ConfigError("--select needs at least one step name")
            return self._dag.select(names, include_upstream=True)
        if from_step is not None:
            self._dag.get(from_step)
            order = self._dag.topological_order()
            return order[order.index(from_step) :]
        return self._dag.topological_order()
