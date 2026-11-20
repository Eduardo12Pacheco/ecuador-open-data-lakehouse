"""Integration tests for the dbt unit tests shipped with the project (S11)."""

from __future__ import annotations

from ecuador_lakehouse.domain.quality import TestStatus as DbtTestStatus

from .conftest import StagingBuild


def test_dbt_unit_tests_pass_and_cover_every_parsing_macro(
    marts_build: StagingBuild,
) -> None:
    summary = marts_build.transformer.test(select="test_type:unit")

    assert summary.total >= 6
    assert summary.failed == 0
    assert all(outcome.status is DbtTestStatus.PASS for outcome in summary.outcomes)
