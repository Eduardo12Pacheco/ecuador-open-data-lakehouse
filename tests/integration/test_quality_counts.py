"""Full dbt quality suite: counts, pass status and a proven failure path (S11, T9)."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import duckdb

from ecuador_lakehouse.adapters.transform.dbt_runner import DbtTransformer
from ecuador_lakehouse.adapters.transform.results import load_json
from ecuador_lakehouse.domain.quality import TestStatus as DbtTestStatus

from .conftest import StagingBuild


def count_results(run_results: Mapping[str, Any]) -> tuple[int, int]:
    """Count data tests and unit tests in one ``run_results.json`` payload."""
    data_tests = 0
    unit_tests = 0
    for result in run_results["results"]:
        unique_id = str(result["unique_id"])
        if unique_id.startswith("test."):
            data_tests += 1
        elif unique_id.startswith("unit_test."):
            unit_tests += 1
    return data_tests, unit_tests


def test_full_quality_suite_counts_and_passes(marts_build: StagingBuild) -> None:
    summary = marts_build.transformer.test()

    assert summary.ok is True
    assert summary.failed == 0
    assert not [outcome for outcome in summary.outcomes if outcome.status is DbtTestStatus.ERROR]
    run_results = load_json(marts_build.transformer.target_dir / "run_results.json")
    data_tests, unit_tests = count_results(run_results)
    assert data_tests >= 60
    assert unit_tests >= 10


def test_a_corrupted_raw_row_makes_the_quality_gate_fail(
    marts_build: StagingBuild,
    tmp_path: Path,
) -> None:
    warehouse_path = tmp_path / "warehouse.duckdb"
    # Copy the built warehouse byte-for-byte, then append one impossible province.
    shutil.copy2(marts_build.warehouse_path, warehouse_path)
    with duckdb.connect(str(warehouse_path)) as connection:
        connection.execute(
            """
            insert into raw.sri_tax_collection (
                anio, mes_label, grupo, subgrupo, impuesto, tipo_contribuyente,
                provincia, canton, valor_raw, _batch_id, _source_file, _source_sha256
            )
            select
                anio, mes_label, grupo, subgrupo, impuesto, tipo_contribuyente,
                'PROVINCIA INEXISTENTE', canton, valor_raw,
                'quality-gate-corruption', _source_file, _source_sha256
            from raw.sri_tax_collection
            where anio = '2025'
            limit 1
            """
        )

    transformer = DbtTransformer(warehouse_path=warehouse_path, home=tmp_path / "home")
    summary = transformer.test(select="stg_sri__tax_collection")

    assert summary.ok is False
    failed = [outcome for outcome in summary.outcomes if outcome.status is DbtTestStatus.FAIL]
    assert failed
    assert any("province_key" in outcome.name for outcome in failed)
