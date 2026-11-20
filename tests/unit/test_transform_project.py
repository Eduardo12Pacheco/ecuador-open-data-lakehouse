"""Unit tests for materializing the packaged dbt project (D18)."""

from __future__ import annotations

from pathlib import Path

from ecuador_lakehouse.adapters.transform.project import copy_project, write_profiles


def test_copies_the_packaged_project_into_the_user_data_directory(tmp_path: Path) -> None:
    destination = tmp_path / "dbt" / "project"

    result = copy_project(destination)

    assert result == destination
    assert (destination / "dbt_project.yml").is_file()
    assert (destination / "macros" / "norm_key.sql").is_file()
    assert (destination / "models" / "staging" / "stg_sri__tax_collection.sql").is_file()
    assert not (destination / "target").exists()
    assert not (destination / "logs").exists()


def test_writes_a_duckdb_profile_with_absolute_paths(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    profiles = tmp_path / "project"

    path = write_profiles(profiles, warehouse_path=warehouse, threads=6)

    text = path.read_text(encoding="utf-8")
    assert path.name == "profiles.yml"
    assert "type: duckdb" in text
    assert f'path: "{warehouse.resolve().as_posix()}"' in text
    assert "threads: 6" in text
    assert "ecuador_lakehouse:" in text
