"""Value objects summarising dbt data and unit test outcomes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class TestStatus(StrEnum):
    """Result of a single dbt test node."""

    PASS = "pass"  # noqa: S105 - a test status, not a secret
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TestOutcome:
    """One dbt test node result, independent of dbt's own result structures."""

    name: str
    status: TestStatus
    message: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("test name must not be empty")

    @property
    def passed(self) -> bool:
        """Whether the node passed."""
        return self.status is TestStatus.PASS


@dataclass(frozen=True, slots=True)
class QualitySummary:
    """Aggregated quality gate used by ``lakehouse test`` and the artifact manifest."""

    outcomes: tuple[TestOutcome, ...] = ()

    @classmethod
    def from_outcomes(cls, outcomes: Iterable[TestOutcome]) -> QualitySummary:
        """Build a summary from any iterable of outcomes."""
        return cls(outcomes=tuple(outcomes))

    @property
    def total(self) -> int:
        """Number of test nodes."""
        return len(self.outcomes)

    @property
    def passed(self) -> int:
        """Number of passing test nodes."""
        return sum(1 for outcome in self.outcomes if outcome.status is TestStatus.PASS)

    @property
    def failed(self) -> int:
        """Number of failing or errored test nodes."""
        return sum(
            1 for outcome in self.outcomes if outcome.status in {TestStatus.FAIL, TestStatus.ERROR}
        )

    @property
    def skipped(self) -> int:
        """Number of skipped test nodes."""
        return sum(1 for outcome in self.outcomes if outcome.status is TestStatus.SKIP)

    @property
    def ok(self) -> bool:
        """Whether the gate is open (no failures or errors)."""
        return self.failed == 0

    @property
    def failed_names(self) -> tuple[str, ...]:
        """Names of failing or errored test nodes, in input order."""
        return tuple(
            outcome.name
            for outcome in self.outcomes
            if outcome.status in {TestStatus.FAIL, TestStatus.ERROR}
        )
