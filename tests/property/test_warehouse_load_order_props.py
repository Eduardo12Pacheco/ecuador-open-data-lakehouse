"""Property test: raw contents are independent of the partition load order (S6)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.conftest import CanonicalSample

from ecuador_lakehouse.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from ecuador_lakehouse.domain.sources import SourceId

RAW_TABLES = (
    "sri_tax_collection",
    "bce_cnt_quarterly",
    "inec_cpi_index",
)


def snapshot(warehouse: DuckDbWarehouse) -> dict[str, list[tuple[object, ...]]]:
    result: dict[str, list[tuple[object, ...]]] = {}
    for table in RAW_TABLES:
        sql = f"SELECT * FROM raw.{table} ORDER BY ALL"  # noqa: S608 - table from a frozen tuple
        result[table] = warehouse.connection.execute(sql).fetchall()
    return result


@settings(max_examples=3, deadline=None)
@given(order=st.permutations(range(12)))
def test_any_load_order_yields_identical_raw_contents(
    order: tuple[int, ...],
    canonical_sample: tuple[CanonicalSample, ...],
) -> None:
    with tempfile.TemporaryDirectory(prefix="lakehouse-load-order-") as tmp:
        tmp_path = Path(tmp)
        first = DuckDbWarehouse(tmp_path / "first.duckdb")
        second = DuckDbWarehouse(tmp_path / "second.duckdb")
        try:
            for position in order:
                entry = canonical_sample[position]
                first.load_partition(
                    entry.source_id, entry.partition, entry.path, entry.sha256, entry.source_file
                )
            for position in reversed(order):
                entry = canonical_sample[position]
                second.load_partition(
                    entry.source_id, entry.partition, entry.path, entry.sha256, entry.source_file
                )
            assert snapshot(first) == snapshot(second)
            assert len(first.ledger()) == len(second.ledger()) == 12

            def identity(warehouse: DuckDbWarehouse) -> list[tuple[object, ...]]:
                return sorted(
                    (
                        record.batch_id,
                        record.source_id,
                        record.partition,
                        record.source_sha256,
                        record.row_count,
                        record.status,
                        record.mode,
                        record.is_current,
                    )
                    for record in warehouse.ledger()
                )

            assert identity(first) == identity(second)
            assert all(record.source_id in SourceId for record in first.ledger())
        finally:
            first.close()
            second.close()
