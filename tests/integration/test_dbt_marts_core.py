"""Integration tests for the star schema: dimensions, facts and SCD2 (S8, S9, S10)."""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest

from ecuador_lakehouse.adapters.transform.dbt_runner import DbtTransformer
from ecuador_lakehouse.domain.quality import TestStatus as DbtTestStatus

from .conftest import StagingBuild


def scalar(warehouse_path: Path, sql: str) -> object:
    """Run one scalar query against a built warehouse read-only."""
    with duckdb.connect(str(warehouse_path), read_only=True) as connection:
        row = connection.execute(sql).fetchone()
    assert row is not None
    return row[0]


def test_dimensions_have_the_expected_cardinality(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path

    assert scalar(warehouse, "select count(*) from marts.dim_date") >= 300
    assert scalar(warehouse, "select count(*) from marts.dim_quarter") == 85
    assert scalar(warehouse, "select count(*) from marts.dim_geography") >= 25
    assert scalar(warehouse, "select count(*) from marts.dim_price_area") == 12
    assert scalar(warehouse, "select count(*) from marts.dim_national_account_item") == 53
    assert scalar(warehouse, "select count(*) from marts.dim_cpi_item") == 633
    assert scalar(warehouse, "select count(distinct tax_item_nk) from marts.dim_tax_item") >= 244


def test_dim_date_spans_the_earliest_and_latest_source_month(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path
    expected = scalar(
        warehouse,
        """
        select min(month_start) || '|' || max(month_start)
        from (
            select min(period_date) as month_start from staging.stg_sri__tax_collection
            union all
            select max(period_date) from staging.stg_sri__tax_collection
            union all
            select min(period_date) from staging.stg_inec__cpi_index
            union all
            select max(period_date) from staging.stg_inec__cpi_index
            union all
            select min(make_date(period_year, (period_quarter - 1) * 3 + 1, 1))
            from staging.stg_bce__national_accounts
            union all
            select max(make_date(period_year, (period_quarter - 1) * 3 + 1, 1))
            from staging.stg_bce__national_accounts
        )
        """,
    )
    actual = scalar(
        warehouse,
        "select min(month_start_date) || '|' || max(month_start_date) from marts.dim_date",
    )

    assert actual == expected


def test_dim_date_months_are_unique_and_contiguous(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path

    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from (select month_key from marts.dim_date group by 1 having count(*) > 1)
            """,
        )
        == 0
    )
    gaps = scalar(
        warehouse,
        """
        select count(*)
        from (
            select month_start_date,
                   lag(month_start_date) over (order by month_start_date) as previous_month
            from marts.dim_date
        )
        where previous_month is not null
          and month_start_date <> previous_month + interval 1 month
        """,
    )
    assert gaps == 0


def test_every_tax_item_has_exactly_one_current_version(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path

    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from (
                select tax_item_nk
                from marts.dim_tax_item
                group by tax_item_nk
                having count(*) filter (where is_current) <> 1
            )
            """,
        )
        == 0
    )
    assert scalar(warehouse, "select count(*) from marts.dim_tax_item where is_current") == scalar(
        warehouse, "select count(distinct tax_item_nk) from marts.dim_tax_item"
    )


def test_scd2_versions_are_contiguous_and_non_overlapping(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path

    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from marts.dim_tax_item
            where valid_from > valid_to
            """,
        )
        == 0
    )
    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from (
                select valid_to,
                       valid_from,
                       lag(valid_to) over (
                           partition by tax_item_nk order by valid_from
                       ) as previous_valid_to
                from marts.dim_tax_item
            )
            where previous_valid_to is not null
              and valid_from <> previous_valid_to + interval 1 day
            """,
        )
        == 0
    )
    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from marts.dim_tax_item
            where is_current <> (valid_to = date '9999-12-31')
            """,
        )
        == 0
    )


def test_fact_tables_have_the_expected_sizes_and_unique_grains(
    marts_build: StagingBuild,
) -> None:
    warehouse = marts_build.warehouse_path

    assert scalar(warehouse, "select count(*) from marts.fct_national_accounts") <= 9_010
    assert scalar(warehouse, "select count(*) from marts.fct_national_accounts") > 0
    assert scalar(warehouse, "select count(*) from marts.fct_cpi_index") == 911_520
    assert scalar(warehouse, "select count(*) from marts.fct_tax_collection") > 0

    duplicate_groups = (
        (
            "fct_tax_collection",
            "period_date, tax_item_key, taxpayer_type, geography_key",
        ),
        ("fct_cpi_index", "period_date, price_area_key, cpi_item_key"),
        ("fct_national_accounts", "quarter_key, account_item_key, price_basis"),
    )
    for table, grain in duplicate_groups:
        sql = (
            f"select count(*) from (select {grain} from marts.{table} "  # noqa: S608
            f"group by {grain} having count(*) > 1)"
        )
        assert scalar(warehouse, sql) == 0, table


def test_2025_tax_collection_reconciles_to_the_control_total(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path
    expected = scalar(
        warehouse,
        """
        select expected_total_usd
        from staging.control_totals
        where source_id = 'sri_tax' and period_year = 2025
        """,
    )
    actual = scalar(
        warehouse,
        "select sum(collected_usd) from marts.fct_tax_collection where period_year = 2025",
    )

    assert isinstance(expected, float | int)
    assert actual is not None
    assert float(actual) == pytest.approx(float(expected), abs=500.0)


def test_every_tax_fact_points_to_an_active_version_valid_at_its_year(
    marts_build: StagingBuild,
) -> None:
    warehouse = marts_build.warehouse_path

    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from marts.fct_tax_collection f
            join marts.dim_tax_item d on d.tax_item_key = f.tax_item_key
            where d.lifecycle_status <> 'active'
               or f.period_year < year(d.valid_from)
               or f.period_year > year(d.valid_to)
            """,
        )
        == 0
    )
    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from marts.fct_tax_collection f
            left join marts.dim_tax_item d on d.tax_item_key = f.tax_item_key
            where d.tax_item_key is null
            """,
        )
        == 0
    )


def test_fact_foreign_keys_resolve(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path
    checks = (
        ("fct_tax_collection", "geography_key", "dim_geography", "geography_key"),
        ("fct_cpi_index", "price_area_key", "dim_price_area", "price_area_key"),
        ("fct_cpi_index", "cpi_item_key", "dim_cpi_item", "cpi_item_key"),
        (
            "fct_national_accounts",
            "account_item_key",
            "dim_national_account_item",
            "account_item_key",
        ),
        ("fct_national_accounts", "quarter_key", "dim_quarter", "quarter_key"),
    )
    for fact, column, dimension, dimension_key in checks:
        sql = f"""
            select count(*)
            from marts.{fact} f
            anti join marts.{dimension} d on f.{column} = d.{dimension_key}
            """  # noqa: S608 - table and column names come from the frozen tuple above
        missing = scalar(warehouse, sql)
        assert missing == 0, f"{fact}.{column}"


def test_dbt_data_tests_on_the_marts_layer_pass(marts_build: StagingBuild) -> None:
    summary = marts_build.transformer.test(select="marts")

    assert summary.total > 0
    assert summary.failed == 0
    assert all(outcome.status is DbtTestStatus.PASS for outcome in summary.outcomes)


def test_removing_a_seed_province_makes_the_relationships_guard_fail(
    marts_build: StagingBuild,
    tmp_path: Path,
) -> None:
    copied_warehouse = tmp_path / "warehouse.duckdb"
    shutil.copy2(marts_build.warehouse_path, copied_warehouse)
    with duckdb.connect(str(copied_warehouse)) as connection:
        connection.execute("delete from staging.ref_province where province_key = 'AZUAY'")

    transformer = DbtTransformer(
        warehouse_path=copied_warehouse,
        home=tmp_path / "home",
        threads=4,
    )
    summary = transformer.test(select="staging")

    failing = [outcome for outcome in summary.outcomes if outcome.status is not DbtTestStatus.PASS]
    assert failing, "the province relationships test must fail when a seed row is removed"
    assert any("province" in outcome.name for outcome in failing)
