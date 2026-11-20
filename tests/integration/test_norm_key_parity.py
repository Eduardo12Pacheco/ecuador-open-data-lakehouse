"""Differential test: Python ``normalize_key`` and SQL ``norm_key`` (D12)."""

from __future__ import annotations

import duckdb

from ecuador_lakehouse.domain.text import normalize_key

from .conftest import StagingBuild

PAIRS = (
    ("tax_group_name", "tax_group_key"),
    ("tax_subgroup_name", "tax_subgroup_key"),
    ("tax_name", "tax_key"),
    ("province_key", "province_key"),
)


def test_python_and_sql_normalization_agree_on_every_sample_label(
    staging_build: StagingBuild,
) -> None:
    connection = duckdb.connect(str(staging_build.warehouse_path), read_only=True)
    try:
        pairs: list[tuple[str, str, str]] = []
        for name_column, key_column in PAIRS:
            if name_column == key_column:
                rows = connection.execute(
                    f"select distinct {name_column} from staging.stg_sri__tax_collection"  # noqa: S608
                ).fetchall()
                pairs.extend((value[0], value[0]) for value in rows)
            else:
                rows = connection.execute(
                    f"select distinct {name_column}, {key_column} "  # noqa: S608
                    "from staging.stg_sri__tax_collection"
                ).fetchall()
                pairs.extend((value[0], value[1]) for value in rows)
        cantons = connection.execute(
            "select distinct canton_name, canton_key from staging.stg_sri__tax_collection "
            "where canton_key is not null"
        ).fetchall()
        pairs.extend((value[0], value[1]) for value in cantons)
    finally:
        connection.close()

    assert pairs
    mismatches = [
        (label, expected, actual)
        for label, actual in pairs
        if (expected := normalize_key(label)) != actual
    ]
    assert mismatches == []
