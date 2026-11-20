"""Property test: the real SCD2 model keeps its invariants on random histories (S10)."""

from __future__ import annotations

import itertools
import tempfile
from datetime import date, timedelta
from pathlib import Path

import duckdb
from hypothesis import given, settings
from hypothesis import strategies as st

from ecuador_lakehouse.adapters.transform.dbt_runner import DbtTransformer
from ecuador_lakehouse.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse

YEARS = tuple(range(2017, 2027))
GROUPS = ("GRUPO UNO", "GRUPO DOS")


@st.composite
def presence_matrices(draw: st.DrawFn) -> list[tuple[str, tuple[bool, ...], tuple[str, ...]]]:
    """Draw 1-2 tax lines with a random presence and group history per year."""
    items: list[tuple[str, tuple[bool, ...], tuple[str, ...]]] = []
    for index in range(draw(st.integers(min_value=1, max_value=2))):
        active = tuple(draw(st.lists(st.booleans(), min_size=len(YEARS), max_size=len(YEARS))))
        if not any(active):
            active = (True, *active[1:])
        groups = tuple(
            draw(st.lists(st.sampled_from(GROUPS), min_size=len(YEARS), max_size=len(YEARS)))
        )
        items.append((f"TAX LINE {index}", active, groups))
    return items


def _insert_history(
    warehouse_path: Path,
    matrix: list[tuple[str, tuple[bool, ...], tuple[str, ...]]],
) -> None:
    rows: list[tuple[object, ...]] = []
    for tax_name, active, groups in matrix:
        for year, present, group in zip(YEARS, active, groups, strict=True):
            if not present:
                continue
            rows.append(
                (
                    str(year),
                    "01 Enero",
                    group,
                    "SUBCATEGORIA",
                    tax_name,
                    "SOCIEDADES",
                    "PICHINCHA",
                    "",
                    "10,00",
                    "property-batch",
                    "property.csv",
                    "0" * 64,
                )
            )
    warehouse = DuckDbWarehouse(warehouse_path)
    try:
        warehouse.connection.executemany(
            "insert into raw.sri_tax_collection values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    finally:
        warehouse.close()


def _assert_invariants(
    warehouse_path: Path,
    matrix: list[tuple[str, tuple[bool, ...], tuple[str, ...]]],
) -> None:
    with duckdb.connect(str(warehouse_path), read_only=True) as connection:
        rows = connection.execute(
            """
            select tax_item_nk, lifecycle_status, valid_from, valid_to, is_current
            from marts.dim_tax_item
            order by tax_item_nk, valid_from
            """
        ).fetchall()
    versions: dict[str, list[tuple[str, date, date, bool]]] = {}
    for natural_key, status, valid_from, valid_to, is_current in rows:
        versions.setdefault(str(natural_key), []).append(
            (str(status), valid_from, valid_to, bool(is_current))
        )
    max_loaded_year = max(
        year
        for _name, active, _groups in matrix
        for year, present in zip(YEARS, active, strict=True)
        if present
    )

    for tax_name, active, _groups in matrix:
        natural_key = f"{tax_name}|SUBCATEGORIA"
        item_versions = versions[natural_key]
        assert sum(1 for version in item_versions if version[3]) == 1
        for previous, current in itertools.pairwise(item_versions):
            assert previous[2] < current[1]
            assert current[1] == previous[2] + timedelta(days=1)
        for year, present in zip(YEARS, active, strict=True):
            if year > max_loaded_year:
                continue
            matching = [
                status
                for status, valid_from, valid_to, _current in item_versions
                if valid_from <= date(year, 1, 1) <= valid_to and status == "active"
            ]
            assert len(matching) == (1 if present else 0), (natural_key, year)


@settings(max_examples=10, deadline=None)
@given(matrix=presence_matrices())
def test_scd2_invariants_hold_on_random_histories(
    matrix: list[tuple[str, tuple[bool, ...], tuple[str, ...]]],
) -> None:
    with tempfile.TemporaryDirectory(prefix="lakehouse-scd2-property-") as tmp:
        home = Path(tmp)
        _insert_history(home / "warehouse.duckdb", matrix)
        transformer = DbtTransformer(
            warehouse_path=home / "warehouse.duckdb",
            home=home,
            threads=4,
        )
        transformer.seed_and_run(select="+dim_tax_item")
        _assert_invariants(home / "warehouse.duckdb", matrix)
