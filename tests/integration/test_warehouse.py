"""Integration tests for the DuckDB raw layer, batch ledger and loader (S6)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.sources.sample_fetcher import SampleSourceFetcher
from ecuador_lakehouse.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from ecuador_lakehouse.application.ports import LoadResult
from ecuador_lakehouse.application.use_cases.acquire import AcquireSources
from ecuador_lakehouse.application.use_cases.load_raw import LoadRaw
from ecuador_lakehouse.config import Settings
from ecuador_lakehouse.container import default_parsers, load_lockfile, load_sample_manifest
from ecuador_lakehouse.domain.batches import BatchStatus, make_batch_id
from ecuador_lakehouse.domain.errors import LakehouseError, SourceSchemaError
from ecuador_lakehouse.domain.sources import SourceId
from tests.conftest import CanonicalSample

SRI_COLUMNS = (
    "anio",
    "mes_label",
    "grupo",
    "subgrupo",
    "impuesto",
    "tipo_contribuyente",
    "provincia",
    "canton",
    "valor_raw",
)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64

SRI_ROWS = (
    (
        "2019",
        "01 Enero",
        "IVA",
        "IVA GENERAL",
        "IVA 15%",
        "SOCIEDADES",
        "PICHINCHA",
        "",
        "83,3100",
    ),
    (
        "2019",
        "02 Febrero",
        "RENTA",
        "RENTA SOCIEDADES",
        "RENTA",
        "SOCIEDADES",
        "GUAYAS",
        "",
        "1,0000",
    ),
)


@dataclass(frozen=True)
class CanonicalFile:
    """One canonical CSV written by the test itself (no production parser involved)."""

    path: Path
    rows: int


def write_canonical(
    directory: Path, name: str, columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...]
) -> CanonicalFile:
    path = directory / f"{name}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)
    return CanonicalFile(path=path, rows=len(rows))


def open_warehouse(tmp_path: Path, *, name: str = "warehouse.duckdb") -> DuckDbWarehouse:
    return DuckDbWarehouse(tmp_path / name)


def raw_rows(warehouse: DuckDbWarehouse, table: str) -> list[tuple[object, ...]]:
    sql = f"SELECT * FROM raw.{table} ORDER BY ALL"  # noqa: S608 - table from a frozen set
    return warehouse.connection.execute(sql).fetchall()


def test_first_load_records_a_loaded_batch_and_the_second_load_is_a_no_op(
    tmp_path: Path,
) -> None:
    warehouse = open_warehouse(tmp_path)
    canonical = write_canonical(tmp_path, "sri_2019", SRI_COLUMNS, SRI_ROWS)

    first = warehouse.load_partition(
        SourceId.SRI_TAX, "2019", canonical.path, SHA_A, "sri_tax_collection_2019.csv.gz"
    )

    assert isinstance(first, LoadResult)
    assert first.status is BatchStatus.LOADED
    assert first.row_count == 2
    assert first.batch_id == make_batch_id(SourceId.SRI_TAX, "2019", SHA_A)
    rows = raw_rows(warehouse, "sri_tax_collection")
    assert len(rows) == 2
    assert {row[-3] for row in rows} == {first.batch_id}
    assert {row[-2] for row in rows} == {"sri_tax_collection_2019.csv.gz"}
    assert {row[-1] for row in rows} == {SHA_A}

    second = warehouse.load_partition(
        SourceId.SRI_TAX, "2019", canonical.path, SHA_A, "sri_tax_collection_2019.csv.gz"
    )

    assert second.status is BatchStatus.SKIPPED
    assert second.batch_id == first.batch_id
    assert second.row_count == 2
    assert len(raw_rows(warehouse, "sri_tax_collection")) == 2
    ledger = warehouse.ledger()
    assert len(ledger) == 1
    assert ledger[0].status is BatchStatus.LOADED
    assert ledger[0].is_current is True
    assert ledger[0].mode == "sample"
    warehouse.close()


def test_changed_checksum_replaces_only_that_partition_and_keeps_other_batches(
    tmp_path: Path,
) -> None:
    warehouse = open_warehouse(tmp_path)
    sri_2019 = write_canonical(tmp_path, "sri_2019", SRI_COLUMNS, SRI_ROWS)
    sri_2020 = write_canonical(
        tmp_path,
        "sri_2020",
        SRI_COLUMNS,
        (
            (
                "2020",
                "01 Enero",
                "IVA",
                "IVA GENERAL",
                "IVA 15%",
                "SOCIEDADES",
                "AZUAY",
                "",
                "2,5000",
            ),
        ),
    )
    first_2019 = warehouse.load_partition(
        SourceId.SRI_TAX, "2019", sri_2019.path, SHA_A, "sri_tax_collection_2019.csv.gz"
    )
    first_2020 = warehouse.load_partition(
        SourceId.SRI_TAX, "2020", sri_2020.path, SHA_B, "sri_tax_collection_2020.csv.gz"
    )
    changed = write_canonical(
        tmp_path,
        "sri_2019_v2",
        SRI_COLUMNS,
        (
            (
                "2019",
                "01 Enero",
                "IVA",
                "IVA GENERAL",
                "IVA 15%",
                "SOCIEDADES",
                "PICHINCHA",
                "",
                "9,9900",
            ),
            (
                "2019",
                "03 Marzo",
                "ICE",
                "ICE CERVEZA",
                "ICE",
                "SOCIEDADES",
                "GUAYAS",
                "",
                "1,0000",
            ),
            (
                "2019",
                "04 Abril",
                "ICE",
                "ICE CERVEZA",
                "ICE",
                "PERSONAS NATURALES",
                "GUAYAS",
                "",
                "2,0000",
            ),
        ),
    )

    replaced = warehouse.load_partition(
        SourceId.SRI_TAX, "2019", changed.path, SHA_C, "sri_tax_collection_2019.csv.gz"
    )

    assert replaced.status is BatchStatus.REPLACED
    assert replaced.batch_id == make_batch_id(SourceId.SRI_TAX, "2019", SHA_C)
    assert replaced.batch_id != first_2019.batch_id
    assert replaced.row_count == 3
    rows_2019 = warehouse.connection.execute(
        "SELECT _batch_id, _source_sha256 FROM raw.sri_tax_collection "
        "WHERE anio = '2019' ORDER BY ALL"
    ).fetchall()
    assert rows_2019 == [(replaced.batch_id, SHA_C)] * 3
    rows_2020 = warehouse.connection.execute(
        "SELECT _batch_id, _source_sha256 FROM raw.sri_tax_collection WHERE anio = '2020'"
    ).fetchall()
    assert rows_2020 == [(first_2020.batch_id, SHA_B)]
    by_partition = {(record.partition, record.batch_id): record for record in warehouse.ledger()}
    assert by_partition[("2019", first_2019.batch_id)].is_current is False
    assert by_partition[("2019", replaced.batch_id)].is_current is True
    assert by_partition[("2020", first_2020.batch_id)].is_current is True
    warehouse.close()


def test_a_bad_canonical_csv_rolls_back_data_and_ledger(tmp_path: Path) -> None:
    warehouse = open_warehouse(tmp_path)
    canonical = write_canonical(tmp_path, "sri_2019", SRI_COLUMNS, SRI_ROWS)
    loaded = warehouse.load_partition(
        SourceId.SRI_TAX, "2019", canonical.path, SHA_A, "sri_tax_collection_2019.csv.gz"
    )
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "anio,mes_label,grupo,subgrupo,impuesto,tipo_contribuyente,provincia,canton,valor_raw\n"
        "2019,01 Enero,IVA,IVA GENERAL,IVA 15%,SOCIEDADES,PICHINCHA,,1,0\n",
        encoding="utf-8",
    )

    with pytest.raises(SourceSchemaError, match="fields"):
        warehouse.load_partition(
            SourceId.SRI_TAX, "2019", bad, SHA_C, "sri_tax_collection_2019.csv.gz"
        )

    ledger = warehouse.ledger()
    assert len(ledger) == 1
    assert ledger[0].batch_id == loaded.batch_id
    assert ledger[0].is_current is True
    rows = warehouse.connection.execute(
        "SELECT _batch_id, _source_sha256 FROM raw.sri_tax_collection"
    ).fetchall()
    assert rows == [(loaded.batch_id, SHA_A), (loaded.batch_id, SHA_A)]
    warehouse.close()


def test_canonical_csv_with_a_wrong_header_is_rejected(tmp_path: Path) -> None:
    warehouse = open_warehouse(tmp_path)
    wrong = tmp_path / "wrong.csv"
    wrong.write_text("anio,mes_label\n2019,01 Enero\n", encoding="utf-8")

    with pytest.raises(SourceSchemaError, match="header"):
        warehouse.load_partition(
            SourceId.SRI_TAX, "2019", wrong, SHA_A, "sri_tax_collection_2019.csv.gz"
        )

    assert warehouse.ledger() == ()
    warehouse.close()


def test_loading_the_full_bundled_sample_into_the_raw_layer(
    canonical_sample: tuple[CanonicalSample, ...], tmp_path: Path
) -> None:
    warehouse = open_warehouse(tmp_path)
    for entry in canonical_sample:
        warehouse.load_partition(
            entry.source_id,
            entry.partition,
            entry.path,
            entry.sha256,
            entry.source_file,
        )

    sri_files = warehouse.connection.execute(
        "SELECT count(DISTINCT _source_file) FROM raw.sri_tax_collection"
    ).fetchone()
    assert sri_files == (10,)
    cpi_areas = warehouse.connection.execute(
        "SELECT count(DISTINCT price_area) FROM raw.inec_cpi_index"
    ).fetchone()
    assert cpi_areas == (12,)
    cpi_rows = warehouse.connection.execute("SELECT count(*) FROM raw.inec_cpi_index").fetchone()
    assert cpi_rows is not None
    assert 500_000 <= cpi_rows[0] <= 1_100_000
    bce_rows = warehouse.connection.execute("SELECT count(*) FROM raw.bce_cnt_quarterly").fetchone()
    assert bce_rows == (32_470,)
    assert len(warehouse.ledger()) == 12
    warehouse.close()


def test_load_raw_use_case_parses_fetched_files_and_reports_each_partition(
    tmp_path: Path,
) -> None:
    settings = Settings(home=tmp_path / "home")
    fetcher = SampleSourceFetcher(load_sample_manifest(), tmp_path / "cache")
    acquire = AcquireSources(fetcher=fetcher, lockfile=load_lockfile())
    fetched = acquire.execute(SourceId.SRI_TAX, ("2019", "2020"))
    warehouse = DuckDbWarehouse(settings.home / "warehouse.duckdb", mode=settings.mode)
    load_raw = LoadRaw(parsers=default_parsers(), warehouse=warehouse)

    results = load_raw.execute(fetched)

    assert [result.partition for result in results] == ["2019", "2020"]
    assert [result.status for result in results] == [BatchStatus.LOADED, BatchStatus.LOADED]
    assert [result.row_count for result in results] == [24_035, 23_839]
    warehouse.close()


def test_schema_declares_the_three_raw_tables_and_metadata_ledgers(tmp_path: Path) -> None:
    warehouse = open_warehouse(tmp_path)

    tables = {
        (schema, name)
        for schema, name in warehouse.connection.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN ('raw', 'meta')"
        ).fetchall()
    }

    assert tables == {
        ("raw", "sri_tax_collection"),
        ("raw", "bce_cnt_quarterly"),
        ("raw", "inec_cpi_index"),
        ("meta", "batches"),
        ("meta", "runs"),
    }
    column_types = warehouse.connection.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'raw' AND table_name = 'sri_tax_collection'"
    ).fetchall()
    assert all(data_type == "VARCHAR" for _name, data_type in column_types)
    names = {name for name, _data_type in column_types}
    assert {"_batch_id", "_source_file", "_source_sha256"} <= names
    warehouse.close()
    warehouse.close()


def test_context_manager_closes_the_database(tmp_path: Path) -> None:
    with DuckDbWarehouse(tmp_path / "warehouse.duckdb") as warehouse:
        assert warehouse.path.name == "warehouse.duckdb"
        assert warehouse.ledger() == ()

    with pytest.raises(LakehouseError, match="closed"):
        _ = warehouse.connection
