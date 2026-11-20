"""Integration tests for the dbt foundation and the three staging models (S7)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from ecuador_lakehouse.container import package_path
from ecuador_lakehouse.domain.quality import TestStatus as DbtTestStatus

from .conftest import StagingBuild


def scalar(warehouse_path: Path, sql: str) -> object:
    """Run one scalar query against the built warehouse read-only."""
    with duckdb.connect(str(warehouse_path), read_only=True) as connection:
        row = connection.execute(sql).fetchone()
    assert row is not None
    return row[0]


def test_staging_row_counts_match_the_bundled_sample(staging_build: StagingBuild) -> None:
    warehouse = staging_build.warehouse_path

    assert scalar(warehouse, "select count(*) from staging.stg_bce__national_accounts") == 32_470
    assert (
        scalar(
            warehouse,
            "select count(value_thousand_usd) from staging.stg_bce__national_accounts",
        )
        == 32_294
    )
    assert (
        scalar(warehouse, "select count(distinct period_year) from staging.stg_sri__tax_collection")
        == 10
    )
    assert (
        scalar(
            warehouse,
            "select min(period_year) || '-' || max(period_year) "
            "from staging.stg_sri__tax_collection",
        )
        == "2017-2026"
    )
    assert (
        scalar(
            warehouse, "select count(distinct province_key) from staging.stg_sri__tax_collection"
        )
        == 25
    )
    assert scalar(warehouse, "select count(*) from staging.ref_province") == 25


def test_staging_provinces_are_all_present_in_the_reference_seed(
    staging_build: StagingBuild,
) -> None:
    missing = scalar(
        staging_build.warehouse_path,
        """
        select count(*)
        from (select distinct province_key from staging.stg_sri__tax_collection) s
        anti join staging.ref_province r on s.province_key = r.province_key
        """,
    )

    assert missing == 0


def test_cpi_national_general_weight_is_one(staging_build: StagingBuild) -> None:
    weight = scalar(
        staging_build.warehouse_path,
        """
        select weight
        from staging.stg_inec__cpi_index
        where price_area_key = 'NACIONAL' and level = 'general'
        limit 1
        """,
    )

    assert weight == pytest.approx(1.0)


def test_dbt_data_tests_on_staging_pass(staging_build: StagingBuild) -> None:
    summary = staging_build.transformer.test(select="staging")

    assert summary.total > 0
    assert summary.failed == 0
    assert all(outcome.status is DbtTestStatus.PASS for outcome in summary.outcomes)


def test_dbt_writes_no_artefacts_inside_the_packaged_project(
    staging_build: StagingBuild,
) -> None:
    project_dir = package_path("dbt_project")

    assert not (project_dir / "target").exists()
    assert not (project_dir / "logs").exists()
    assert (staging_build.home / "dbt" / "target" / "manifest.json").is_file()
