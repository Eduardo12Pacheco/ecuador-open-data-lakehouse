"""Tests for the quality-gate summary value objects."""

from __future__ import annotations

import pytest

from ecuador_lakehouse.domain import quality

Outcome = quality.TestOutcome
Status = quality.TestStatus
Kind = quality.TestKind
QualitySummary = quality.QualitySummary


def outcome(name: str, status: Status = Status.PASS, kind: Kind = Kind.DATA) -> Outcome:
    return Outcome(name=name, status=status, kind=kind)


def test_test_status_values_are_stable() -> None:
    assert [status.value for status in Status] == ["pass", "fail", "skip", "error"]


def test_summary_counts_each_status() -> None:
    summary = QualitySummary(
        outcomes=(
            outcome("a"),
            outcome("b"),
            outcome("c", Status.FAIL),
            outcome("d", Status.SKIP),
            outcome("e", Status.ERROR),
        )
    )

    assert summary.total == 5
    assert summary.passed == 2
    assert summary.failed == 2
    assert summary.skipped == 1
    assert summary.ok is False
    assert summary.failed_names == ("c", "e")


def test_summary_is_ok_when_every_test_passes_or_is_skipped() -> None:
    summary = QualitySummary.from_outcomes([outcome("a"), outcome("b", Status.SKIP)])

    assert summary.ok is True
    assert summary.failed == 0
    assert summary.failed_names == ()


def test_empty_summary_is_ok_and_has_zero_counts() -> None:
    summary = QualitySummary(outcomes=())

    assert (summary.total, summary.passed, summary.failed, summary.skipped) == (0, 0, 0, 0)
    assert summary.ok is True


def test_outcome_requires_a_name_and_message_defaults_to_empty() -> None:
    result = Outcome(name="not_null_fct", status=Status.PASS)

    assert result.message == ""
    assert result.passed is True

    with pytest.raises(ValueError, match="name"):
        Outcome(name="", status=Status.PASS)


def test_summary_splits_data_and_unit_tests() -> None:
    summary = QualitySummary.from_outcomes(
        [
            outcome("not_null_x"),
            outcome("unique_y", Status.FAIL),
            outcome("unit_a", kind=Kind.UNIT),
            outcome("unit_b", Status.SKIP, kind=Kind.UNIT),
        ]
    )

    assert summary.data_tests_total == 2
    assert summary.data_tests_passed == 1
    assert summary.unit_tests_total == 2
    assert summary.unit_tests_passed == 1
    assert summary.total == 4


def test_outcome_kind_defaults_to_data() -> None:
    assert Outcome(name="x", status=Status.PASS).kind is Kind.DATA
