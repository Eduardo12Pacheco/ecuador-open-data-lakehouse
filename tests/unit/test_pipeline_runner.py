"""Tests for the custom DAG runner: order, selection, retries and the run ledger."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from ecuador_lakehouse.application.pipeline import PipelineRunner, RetryPolicy, StepContext
from ecuador_lakehouse.application.ports import RunLedger
from ecuador_lakehouse.domain.dag import Dag, DagError, Step
from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.runs import RunRecord, StepResult, StepStatus

DAG = Dag(
    [
        Step("acquire"),
        Step("load_raw", ("acquire",)),
        Step("transform", ("load_raw",)),
        Step("quality", ("transform",)),
        Step("docs", ("quality",)),
        Step("report", ("docs",)),
    ]
)


class FakeLedger(RunLedger):
    """In-memory implementation of the run-ledger port."""

    def __init__(self) -> None:
        self.records: list[RunRecord] = []

    def record_run(self, record: RunRecord) -> None:
        self.records.append(record)

    def runs(self) -> tuple[RunRecord, ...]:
        return tuple(self.records)


def ok(name: str, **metrics: int) -> StepResult:
    return StepResult(name=name, status=StepStatus.OK, duration_s=0.0, metrics=metrics)


def make_runner(
    ledger: FakeLedger | None = None,
    *,
    overrides: dict[str, object] | None = None,
    retry_policies: dict[str, RetryPolicy] | None = None,
) -> PipelineRunner:
    calls: list[str] = []
    steps: dict[str, object] = {}

    def executor(name: str):
        def run(_context: StepContext) -> StepResult:
            calls.append(name)
            return ok(name, calls=len(calls))

        return run

    for step in DAG.steps:
        steps[step.name] = executor(step.name)
    if overrides:
        steps.update(overrides)
    runner = PipelineRunner(
        DAG,
        steps,  # type: ignore[arg-type]
        ledger if ledger is not None else FakeLedger(),
        mode="sample",
        idempotent_steps=frozenset({"acquire"}),
        retry_policies=retry_policies,
        clock=lambda: datetime(2026, 11, 20, tzinfo=UTC).replace(tzinfo=None),
        run_id_factory=lambda: "run-test",
        timer=lambda: 0.0,
    )
    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def executed(runner: PipelineRunner) -> list[str]:
    return list(runner.calls)


def test_default_run_executes_every_step_in_topological_order() -> None:
    ledger = FakeLedger()
    runner = make_runner(ledger)

    report = runner.run()

    assert executed(runner) == ["acquire", "load_raw", "transform", "quality", "docs", "report"]
    assert report.ok is True
    assert [step.name for step in report.steps] == executed(runner)
    assert len(ledger.records) == 1
    assert ledger.records[0].run_id == "run-test"
    assert ledger.records[0].mode == "sample"
    assert '"name":"report"' in ledger.records[0].steps_json()


def test_only_runs_a_single_step() -> None:
    runner = make_runner()

    report = runner.run(only="quality")

    assert executed(runner) == ["quality"]
    assert [step.name for step in report.steps] == ["quality"]


def test_select_includes_transitive_upstream() -> None:
    runner = make_runner()

    report = runner.run(select=["report"])

    assert executed(runner) == ["acquire", "load_raw", "transform", "quality", "docs", "report"]
    assert [step.name for step in report.steps] == executed(runner)


def test_select_a_middle_step_runs_only_its_upstream() -> None:
    runner = make_runner()

    runner.run(select=["quality"])

    assert executed(runner) == ["acquire", "load_raw", "transform", "quality"]


def test_from_step_runs_the_step_and_its_downstream() -> None:
    runner = make_runner()

    runner.run(from_step="docs")

    assert executed(runner) == ["docs", "report"]


def test_unknown_only_step_raises_dag_error() -> None:
    runner = make_runner()

    with pytest.raises(DagError, match="unknown step"):
        runner.run(only="bogus")


def test_unknown_from_step_raises_dag_error() -> None:
    runner = make_runner()

    with pytest.raises(DagError, match="unknown step"):
        runner.run(from_step="bogus")


def test_selection_modes_are_mutually_exclusive() -> None:
    runner = make_runner()

    with pytest.raises(ConfigError, match="mutually exclusive"):
        runner.run(select=["quality"], only="quality")


def test_empty_select_is_rejected() -> None:
    runner = make_runner()

    with pytest.raises(ConfigError, match="at least one step"):
        runner.run(select=[])


def test_failure_stops_downstream_and_is_recorded() -> None:
    ledger = FakeLedger()

    def fail(_context: StepContext) -> StepResult:
        raise ConfigError("boom")

    runner = make_runner(ledger, overrides={"transform": fail})

    with pytest.raises(ConfigError, match="boom"):
        runner.run()

    assert len(ledger.records) == 1
    record = ledger.records[0]
    assert record.status.value == "failed"
    assert [step.name for step in record.steps] == ["acquire", "load_raw", "transform"]
    assert [step.status for step in record.steps] == [
        StepStatus.OK,
        StepStatus.OK,
        StepStatus.FAILED,
    ]
    assert "boom" in record.steps[-1].detail


def test_retry_makes_an_idempotent_step_succeed_after_transient_failures() -> None:
    attempts: list[int] = []
    sleeps: list[float] = []

    def flaky(_context: StepContext) -> StepResult:
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise ConfigError("transient")
        return ok("acquire", fetched=12)

    runner = PipelineRunner(
        DAG,
        {
            "acquire": flaky,
            "load_raw": lambda _context: ok("load_raw"),
            "transform": lambda _context: ok("transform"),
            "quality": lambda _context: ok("quality"),
            "docs": lambda _context: ok("docs"),
            "report": lambda _context: ok("report"),
        },
        FakeLedger(),
        mode="sample",
        idempotent_steps=frozenset({"acquire"}),
        retry_policies={"acquire": RetryPolicy(max_attempts=3, delay_s=0.01)},
        clock=lambda: datetime(2026, 11, 20, tzinfo=UTC).replace(tzinfo=None),
        run_id_factory=lambda: "run-retry",
        sleep=sleeps.append,
        timer=lambda: 0.0,
    )

    report = runner.run(select=["acquire"])

    assert len(attempts) == 3
    assert sleeps == [0.01, 0.01]
    assert report.steps[0].attempts == 3
    assert report.metrics("acquire") == {"fetched": 12}


def test_retry_policy_is_rejected_for_a_non_idempotent_step() -> None:
    with pytest.raises(ConfigError, match="idempotent"):
        make_runner(retry_policies={"load_raw": RetryPolicy(max_attempts=2)})


def test_retry_policy_for_unknown_step_is_rejected() -> None:
    with pytest.raises(ConfigError, match="unknown pipeline step"):
        make_runner(retry_policies={"bogus": RetryPolicy(max_attempts=2)})


def test_retry_policy_with_a_single_attempt_is_rejected() -> None:
    with pytest.raises(ConfigError, match="at least 2 attempts"):
        make_runner(retry_policies={"acquire": RetryPolicy(max_attempts=1)})


def test_missing_executor_is_rejected() -> None:
    with pytest.raises(ConfigError, match="no executor"):
        PipelineRunner(DAG, {}, FakeLedger(), mode="sample")


def test_executor_for_an_unknown_step_is_rejected() -> None:
    steps = {step.name: (lambda _context, name=step.name: ok(name)) for step in DAG.steps}
    steps["bogus"] = lambda _context: ok("bogus")

    with pytest.raises(ConfigError, match="unknown pipeline steps"):
        PipelineRunner(DAG, steps, FakeLedger(), mode="sample")


def test_step_outputs_are_shared_through_the_context() -> None:
    seen: list[object] = []

    def acquire(context: StepContext) -> StepResult:
        context.outputs["acquire"] = ["a", "b"]
        return ok("acquire")

    def load(context: StepContext) -> StepResult:
        seen.extend(context.output("acquire"))
        return ok("load_raw")

    runner = PipelineRunner(
        DAG,
        {
            "acquire": acquire,
            "load_raw": load,
            "transform": lambda _context: ok("transform"),
            "quality": lambda _context: ok("quality"),
            "docs": lambda _context: ok("docs"),
            "report": lambda _context: ok("report"),
        },
        FakeLedger(),
        mode="sample",
        clock=lambda: datetime(2026, 11, 20, tzinfo=UTC).replace(tzinfo=None),
        run_id_factory=lambda: "run-outputs",
        timer=lambda: 0.0,
    )

    runner.run(select=["load_raw"])

    assert seen == ["a", "b"]


def test_reading_an_output_that_did_not_run_is_a_config_error() -> None:
    context = StepContext(run_id="run", mode="sample")

    with pytest.raises(ConfigError, match="did not run"):
        context.output("acquire")


def test_step_must_return_a_step_result() -> None:
    runner = PipelineRunner(
        DAG,
        {
            "acquire": lambda _context: None,  # type: ignore[return-value,arg-type]
            "load_raw": lambda _context: ok("load_raw"),
            "transform": lambda _context: ok("transform"),
            "quality": lambda _context: ok("quality"),
            "docs": lambda _context: ok("docs"),
            "report": lambda _context: ok("report"),
        },
        FakeLedger(),
        mode="sample",
        clock=lambda: datetime(2026, 11, 20, tzinfo=UTC).replace(tzinfo=None),
        run_id_factory=lambda: "run-bad",
        timer=lambda: 0.0,
    )

    with pytest.raises(ConfigError, match="StepResult"):
        runner.run(only="acquire")


def test_empty_run_id_factory_is_rejected() -> None:
    runner = PipelineRunner(
        DAG,
        {step.name: (lambda _context, name=step.name: ok(name)) for step in DAG.steps},
        FakeLedger(),
        mode="sample",
        run_id_factory=lambda: " ",
    )

    with pytest.raises(ConfigError, match="empty id"):
        runner.run(only="quality")


def test_metrics_of_a_step_that_did_not_run_raise() -> None:
    runner = make_runner()

    report = runner.run(only="quality")

    with pytest.raises(ConfigError, match="did not run"):
        report.metrics("acquire")


def test_dag_property_exposes_the_graph() -> None:
    runner = make_runner()

    assert runner.dag.topological_order()[0] == "acquire"


def test_run_report_status_and_steps() -> None:
    runner = make_runner()

    report = runner.run(only="quality")

    assert report.status.value == "ok"
    assert isinstance(report.steps, tuple)


def test_sequence_of_select_names_is_accepted() -> None:
    runner = make_runner()

    runner.run(select=("quality",))

    assert executed(runner)[-1] == "quality"


def test_bad_retry_policy_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValueError, match="delay_s"):
        RetryPolicy(delay_s=-1)


def test_runner_rejects_an_empty_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        PipelineRunner(DAG, {}, FakeLedger(), mode=" ")


def test_select_from_an_empty_sequence_is_typed() -> None:
    runner = make_runner()
    selection: Sequence[str] = ("docs",)

    runner.run(select=selection)

    assert executed(runner) == ["acquire", "load_raw", "transform", "quality", "docs"]


def test_default_steps_can_exclude_optional_steps() -> None:
    dag = Dag(
        [
            Step("acquire"),
            Step("quality", ("acquire",)),
            Step("publish", ("quality",)),
        ]
    )
    called: list[str] = []

    def executor(name: str):
        def run(_context: StepContext) -> StepResult:
            called.append(name)
            return ok(name)

        return run

    runner = PipelineRunner(
        dag,
        {step.name: executor(step.name) for step in dag.steps},
        FakeLedger(),
        mode="sample",
        default_steps=frozenset({"acquire", "quality"}),
        clock=lambda: datetime(2026, 11, 20, tzinfo=UTC).replace(tzinfo=None),
        run_id_factory=lambda: "run-test",
        timer=lambda: 0.0,
    )

    runner.run()
    assert called == ["acquire", "quality"]

    selected = runner.run(select=["publish"])
    assert selected.steps[-1].name == "publish"
    assert called == ["acquire", "quality", "acquire", "quality", "publish"]


def test_default_steps_must_be_registered_steps() -> None:
    with pytest.raises(ConfigError, match="default steps"):
        PipelineRunner(
            DAG,
            {step.name: (lambda _context: ok("x")) for step in DAG.steps},
            FakeLedger(),
            mode="sample",
            default_steps=frozenset({"acquire", "bogus"}),
        )
