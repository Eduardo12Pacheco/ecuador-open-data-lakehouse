"""Unit tests for the report reader error boundaries (S16)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.report.reader import DuckDbReportReader
from ecuador_lakehouse.domain.errors import ConfigError


def test_missing_warehouse_is_a_config_error(tmp_path: Path) -> None:
    reader = DuckDbReportReader(
        warehouse_path=tmp_path / "warehouse.duckdb",
        dbt_target_dir=tmp_path / "dbt" / "target",
    )
    with pytest.raises(ConfigError, match="lakehouse build"):
        reader.read(mode="sample")


def test_warehouse_without_marts_is_a_config_error(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    warehouse.write_bytes(b"")
    reader = DuckDbReportReader(
        warehouse_path=warehouse,
        dbt_target_dir=tmp_path / "dbt" / "target",
    )
    with pytest.raises(ConfigError, match="lakehouse build"):
        reader.read(mode="sample")
