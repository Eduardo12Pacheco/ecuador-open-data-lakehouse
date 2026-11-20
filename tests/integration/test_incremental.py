"""Incremental fact test: only the replaced partition's rows are rewritten (S9, D17)."""

from __future__ import annotations

import csv
import hashlib
import shutil
from pathlib import Path

import duckdb

from ecuador_lakehouse.adapters.transform.dbt_runner import DbtTransformer
from ecuador_lakehouse.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from ecuador_lakehouse.domain.batches import make_batch_id
from ecuador_lakehouse.domain.sources import SourceId
from tests.conftest import CanonicalSample

from .conftest import StagingBuild


def snapshot(warehouse_path: Path) -> tuple[list[tuple[object, ...]], dict[int, float]]:
    """Return the (year, batch) identity of every partition and the yearly totals."""
    with duckdb.connect(str(warehouse_path), read_only=True) as connection:
        identities = connection.execute(
            """
            select period_year, _batch_id, count(*)
            from marts.fct_tax_collection
            group by period_year, _batch_id
            order by period_year
            """
        ).fetchall()
        totals = {
            int(year): float(total)
            for year, total in connection.execute(
                """
                select period_year, sum(collected_usd)
                from marts.fct_tax_collection
                group by period_year
                order by period_year
                """
            ).fetchall()
        }
    return identities, totals


def test_replacing_the_2026_partition_rewrites_only_2026(
    marts_build: StagingBuild,
    canonical_sample: tuple[CanonicalSample, ...],
    tmp_path: Path,
) -> None:
    source = next(
        entry
        for entry in canonical_sample
        if entry.source_id is SourceId.SRI_TAX and entry.partition == "2026"
    )
    before_identities, before_totals = snapshot(marts_build.warehouse_path)

    with source.path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        assert fieldnames is not None
        rows = list(reader)
    assert rows
    extra = dict(rows[0])
    extra["valor_raw"] = "1234,56"
    grown_csv = tmp_path / "sri_2026_grown.csv"
    with grown_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([*rows, extra])
    grown_sha256 = hashlib.sha256(grown_csv.read_bytes()).hexdigest()

    copied_warehouse = tmp_path / "warehouse.duckdb"
    shutil.copy2(marts_build.warehouse_path, copied_warehouse)
    warehouse = DuckDbWarehouse(copied_warehouse)
    try:
        result = warehouse.load_partition(
            SourceId.SRI_TAX, "2026", grown_csv, grown_sha256, source.source_file
        )
    finally:
        warehouse.close()
    assert result.status.value == "replaced"

    transformer = DbtTransformer(
        warehouse_path=copied_warehouse,
        home=tmp_path / "home",
        threads=4,
    )
    transformer.seed_and_run(select="fct_tax_collection")

    after_identities, after_totals = snapshot(copied_warehouse)
    new_batch_id = make_batch_id(SourceId.SRI_TAX, "2026", grown_sha256)

    untouched_before = [row for row in before_identities if row[0] != 2026]
    untouched_after = [row for row in after_identities if row[0] != 2026]
    assert untouched_after == untouched_before

    rewritten = [row for row in after_identities if row[0] == 2026]
    assert len(rewritten) == 1
    assert rewritten[0][1] == new_batch_id
    assert rewritten[0][2] == next(row[2] for row in before_identities if row[0] == 2026)
    assert after_totals[2026] == before_totals[2026] + 1234.56
    for year, total in before_totals.items():
        if year != 2026:
            assert after_totals[year] == total
