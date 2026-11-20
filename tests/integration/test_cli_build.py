"""End-to-end tests for the wired CLI: build, test and the run ledger (S1, S13)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from ecuador_lakehouse.cli.app import app
from ecuador_lakehouse.config import get_settings

runner = CliRunner()
STEP_NAMES = ("acquire", "load_raw", "transform", "quality", "docs", "report")


@dataclass(frozen=True, slots=True)
class CliBuild:
    """A fully built sample lakehouse produced through the real CLI."""

    home: Path
    output: str


@pytest.fixture(scope="module")
def cli_build(tmp_path_factory: pytest.TempPathFactory) -> CliBuild:
    """Run ``lakehouse build`` once on a fresh home and keep it for the module."""
    home = tmp_path_factory.mktemp("cli-build-home")
    get_settings.cache_clear()
    result = runner.invoke(app, ["build"], env={"LAKEHOUSE_HOME": str(home)})
    get_settings.cache_clear()
    assert result.exit_code == 0, result.output + str(result.exception)
    return CliBuild(home=home, output=result.output)


def test_build_runs_every_step_and_loads_twelve_partitions(cli_build: CliBuild) -> None:
    for step in STEP_NAMES:
        assert step in cli_build.output
    assert "12 partitions acquired" in cli_build.output
    assert "12 loaded, 0 skipped, 0 replaced" in cli_build.output
    assert "tests passed" in cli_build.output
    assert (cli_build.home / "warehouse.duckdb").is_file()
    assert (cli_build.home / "site" / "lineage" / "index.html").is_file()
    assert (cli_build.home / "site" / "report.json").is_file()


def test_run_ledger_contains_the_build(cli_build: CliBuild) -> None:
    connection = duckdb.connect(str(cli_build.home / "warehouse.duckdb"), read_only=True)
    try:
        rows = connection.execute(
            "SELECT status, mode, steps_json FROM meta.runs ORDER BY started_at"
        ).fetchall()
    finally:
        connection.close()

    assert len(rows) == 1
    status, mode, steps_json = rows[0]
    assert status == "ok"
    assert mode == "sample"
    assert all(f'"name":"{step}"' in steps_json for step in STEP_NAMES)


def test_second_load_in_the_same_home_skips_every_partition(cli_build: CliBuild) -> None:
    get_settings.cache_clear()
    result = runner.invoke(
        app,
        ["build", "--select", "load_raw"],
        env={"LAKEHOUSE_HOME": str(cli_build.home)},
    )
    get_settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert "0 loaded, 12 skipped, 0 replaced" in result.output
    assert "transform" not in result.output


def test_lakehouse_test_reports_pass_counts(cli_build: CliBuild) -> None:
    get_settings.cache_clear()
    result = runner.invoke(app, ["test"], env={"LAKEHOUSE_HOME": str(cli_build.home)})
    get_settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert "PASS " in result.output
    assert "/" in result.output
    assert "data and unit tests" in result.output


def test_build_only_quality_runs_a_single_step(cli_build: CliBuild) -> None:
    get_settings.cache_clear()
    result = runner.invoke(
        app,
        ["build", "--only", "quality"],
        env={"LAKEHOUSE_HOME": str(cli_build.home)},
    )
    get_settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert "quality" in result.output
    assert "acquire" not in result.output


def test_corrupted_warehouse_closes_the_quality_gate(cli_build: CliBuild, tmp_path: Path) -> None:
    home = tmp_path / "corrupted-home"
    home.mkdir()
    shutil.copyfile(cli_build.home / "warehouse.duckdb", home / "warehouse.duckdb")
    connection = duckdb.connect(str(home / "warehouse.duckdb"))
    try:
        connection.execute(
            "UPDATE raw.sri_tax_collection SET provincia = 'ZZZ IMPOSSIBLE' "
            "WHERE _source_file LIKE '%sri_tax_collection_2019%' AND provincia = 'PICHINCHA'"
        )
    finally:
        connection.close()

    get_settings.cache_clear()
    result = runner.invoke(app, ["test"], env={"LAKEHOUSE_HOME": str(home)})
    get_settings.cache_clear()

    assert result.exit_code == 7, result.output
    assert "quality gate failed" in result.output
    assert "relationships_stg_sri__tax_collection_province_key" in result.output
