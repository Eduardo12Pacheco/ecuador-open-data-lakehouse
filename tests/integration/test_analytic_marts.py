"""Integration tests for the analytic marts (T9).

Every assertion is computed from the built sample warehouse through the
``DbtTransformer`` used by production, so these tests prove the same SQL that
ships in the wheel.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from .conftest import StagingBuild

CPI_VINTAGE_END = "2024-12-01"
SAMPLE_END = "2026-10-01"


def scalar(warehouse_path: Path, sql: str) -> object:
    """Run one scalar query against a built warehouse read-only."""
    with duckdb.connect(str(warehouse_path), read_only=True) as connection:
        row = connection.execute(sql).fetchone()
    assert row is not None
    return row[0]


def test_marts_exist_with_the_expected_grain(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path

    assert scalar(warehouse, "select count(*) from marts.mart_tax_collection_monthly") > 0
    assert scalar(warehouse, "select count(*) from marts.mart_inflation_monthly") > 0
    assert scalar(warehouse, "select count(*) from marts.mart_tax_to_gdp_annual") > 0
    assert scalar(warehouse, "select count(*) from marts.mart_tax_lifecycle") > 0

    assert (
        scalar(
            warehouse,
            """
            select count(*) from (
                select period_date, tax_group_key
                from marts.mart_tax_collection_monthly
                group by 1, 2 having count(*) > 1
            )
            """,
        )
        == 0
    )
    assert (
        scalar(
            warehouse,
            """
            select count(*) from (
                select period_date, price_area_key, cpi_item_key
                from marts.mart_inflation_monthly
                group by 1, 2, 3 having count(*) > 1
            )
            """,
        )
        == 0
    )


def test_tax_monthly_totals_match_the_fact(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path

    mismatches = scalar(
        warehouse,
        """
        select count(*)
        from (
            select m.period_year, sum(m.nominal_usd) as mart_total
            from marts.mart_tax_collection_monthly as m
            group by 1
        ) as mart
        full outer join (
            select period_year, sum(collected_usd) as fact_total
            from marts.fct_tax_collection
            group by 1
        ) as fact using (period_year)
        where mart.mart_total is null
           or fact.fact_total is null
           or abs(mart.mart_total - fact.fact_total) > 0.02
        """,
    )
    assert mismatches == 0


def test_tax_monthly_deflates_only_where_the_cpi_vintage_covers(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path

    assert (
        scalar(
            warehouse,
            """
            select min(period_date) || '|' || max(period_date)
            from marts.mart_tax_collection_monthly
            where real_usd_2014 is not null
            """,
        )
        == f"2017-01-01|{CPI_VINTAGE_END}"
    )
    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from marts.mart_tax_collection_monthly
            where period_date > date '2024-12-01' and real_usd_2014 is not null
            """,
        )
        == 0
    )
    assert (
        scalar(
            warehouse,
            """
        select count(*)
        from marts.mart_tax_collection_monthly
        where period_date <= date '2024-12-01' and real_usd_2014 is null
        """,
        )
        == 0
    )


def test_tax_monthly_shares_and_yoy_are_well_formed(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path

    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from (
                select period_date, sum(share_of_month) as total_share
                from marts.mart_tax_collection_monthly
                group by 1
            )
            where abs(total_share - 1.0) > 1e-9
            """,
        )
        == 0
    )
    assert (
        scalar(
            warehouse,
            """
        select count(*)
        from marts.mart_tax_collection_monthly
        where period_year = 2017 and yoy_nominal is not null
        """,
        )
        == 0
    )
    assert (
        scalar(
            warehouse,
            """
        select count(*)
        from marts.mart_tax_collection_monthly
        where period_year = 2018 and yoy_nominal is not null
        """,
        )
        > 0
    )
    assert (
        scalar(
            warehouse,
            "select max(period_date) from marts.mart_tax_collection_monthly",
        ).isoformat()
        == SAMPLE_END
    )


def test_inflation_mart_covers_general_and_divisions(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path

    assert (
        scalar(
            warehouse,
            "select string_agg(distinct level, ',' order by level) "
            "from marts.mart_inflation_monthly",
        )
        == "division,general"
    )
    assert (
        scalar(
            warehouse,
            "select min(period_date) || '|' || max(period_date) from marts.mart_inflation_monthly",
        )
        == f"2015-01-01|{CPI_VINTAGE_END}"
    )
    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from (
                select period_date, price_area_key
                from marts.mart_inflation_monthly
                group by 1, 2 having count(distinct cpi_item_key) <> 13
            )
            """,
        )
        == 0
    )
    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from marts.mart_inflation_monthly as current
            left join marts.mart_inflation_monthly as previous
                on previous.price_area_key = current.price_area_key
                and previous.cpi_item_key = current.cpi_item_key
                and previous.period_date = current.period_date - interval 1 month
            where current.mom is not null and previous.index_value is null
            """,
        )
        == 0
    )


def test_tax_to_gdp_annual_reports_four_complete_years(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path

    assert (
        scalar(
            warehouse,
            "select count(*) from marts.mart_tax_to_gdp_annual where is_complete",
        )
        == 4
    )
    assert (
        scalar(
            warehouse,
            "select count(*) from marts.mart_tax_to_gdp_annual "
            "where is_complete and period_year between 2017 and 2020",
        )
        == 4
    )
    assert (
        scalar(
            warehouse,
            "select is_complete from marts.mart_tax_to_gdp_annual where period_year = 2021",
        )
        is False
    )
    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from marts.mart_tax_to_gdp_annual
            where is_complete and (ratio < 0.05 or ratio > 0.25)
            """,
        )
        == 0
    )
    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from marts.mart_tax_to_gdp_annual
            where is_complete and quarters_available = 4 and months_available = 12
            """,
        )
        == 4
    )


def test_tax_lifecycle_summarizes_every_natural_key(marts_build: StagingBuild) -> None:
    warehouse = marts_build.warehouse_path

    assert scalar(
        warehouse,
        "select count(*) from marts.mart_tax_lifecycle",
    ) == scalar(
        warehouse,
        "select count(distinct tax_item_nk) from marts.dim_tax_item",
    )
    assert (
        scalar(
            warehouse,
            "select count(*) from marts.mart_tax_lifecycle where first_year > last_year",
        )
        == 0
    )
    assert (
        scalar(
            warehouse,
            "select count(*) from marts.mart_tax_lifecycle where versions_count < 1",
        )
        == 0
    )
    total_gap = scalar(
        warehouse,
        """
        select abs(
            (select sum(total_collected_usd) from marts.mart_tax_lifecycle)
            - (select sum(collected_usd) from marts.fct_tax_collection)
        )
        """,
    )
    assert float(total_gap) < 0.02
    assert (
        scalar(
            warehouse,
            """
            select count(*)
            from marts.mart_tax_lifecycle
            where current_status not in ('active', 'inactive')
            """,
        )
        == 0
    )
