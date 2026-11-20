"""End-to-end tests for the artifact CLI: build --publish, verify and contract (S14)."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from ecuador_lakehouse.cli.app import app
from ecuador_lakehouse.config import get_settings

runner = CliRunner()
EXAMPLE = Path("examples/consume_artifact.py")


@dataclass(frozen=True, slots=True)
class PublishedBuild:
    """A sample lakehouse built and published through the real CLI."""

    home: Path
    artifact: Path
    output: str


@pytest.fixture(scope="module")
def published_build(tmp_path_factory: pytest.TempPathFactory) -> PublishedBuild:
    home = tmp_path_factory.mktemp("artifact-cli-home")
    out = tmp_path_factory.mktemp("artifact-cli-out")
    get_settings.cache_clear()
    result = runner.invoke(
        app,
        ["build", "--publish", "--out", str(out)],
        env={"LAKEHOUSE_HOME": str(home)},
    )
    get_settings.cache_clear()
    assert result.exit_code == 0, result.output + str(result.exception)
    return PublishedBuild(
        home=home,
        artifact=out / "ecuador-lakehouse-1.0.0",
        output=result.output,
    )


def test_build_publish_reports_the_publish_step(published_build: PublishedBuild) -> None:
    assert "publish" in published_build.output
    assert "14 tables at ecuador-lakehouse-1.0.0" in published_build.output
    assert (published_build.artifact / "manifest.json").is_file()
    assert (published_build.artifact / "SHA256SUMS").is_file()


def test_verify_command_accepts_the_artifact(published_build: PublishedBuild) -> None:
    get_settings.cache_clear()
    result = runner.invoke(app, ["verify", str(published_build.artifact)])
    get_settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert "verified 14 tables" in result.output


def test_verify_command_exits_eight_on_tampering(
    published_build: PublishedBuild, tmp_path: Path
) -> None:
    tampered = tmp_path / published_build.artifact.name
    shutil.copytree(published_build.artifact, tampered)
    parquet = tampered / "parquet" / "dim_date.parquet"
    data = bytearray(parquet.read_bytes())
    data[0] ^= 0xFF
    parquet.write_bytes(bytes(data))

    get_settings.cache_clear()
    result = runner.invoke(app, ["verify", str(tampered)])
    get_settings.cache_clear()

    assert result.exit_code == 8, result.output
    assert "SHA-256" in result.output


def test_contract_check_matches_the_committed_contract(published_build: PublishedBuild) -> None:
    get_settings.cache_clear()
    result = runner.invoke(
        app,
        ["contract", "check"],
        env={"LAKEHOUSE_HOME": str(published_build.home)},
    )
    get_settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert "contract 1.0.0 matches 14 warehouse tables" in result.output


def test_contract_check_reports_breaking_drift(
    published_build: PublishedBuild, tmp_path: Path
) -> None:
    contract = json.loads(
        Path("src/ecuador_lakehouse/artifact_contract.json").read_text(encoding="utf-8")
    )
    contract["tables"][0]["columns"][0]["name"] = "renamed_column"
    broken = tmp_path / "broken-contract.json"
    broken.write_text(json.dumps(contract), encoding="utf-8")

    get_settings.cache_clear()
    result = runner.invoke(
        app,
        ["contract", "check", "--contract", str(broken)],
        env={"LAKEHOUSE_HOME": str(published_build.home)},
    )
    get_settings.cache_clear()

    assert result.exit_code == 8, result.output
    assert "MAJOR" in result.output


def test_standalone_publish_reuses_the_warehouse(
    published_build: PublishedBuild, tmp_path: Path
) -> None:
    out = tmp_path / "republished"
    get_settings.cache_clear()
    result = runner.invoke(
        app,
        ["publish", "--out", str(out)],
        env={"LAKEHOUSE_HOME": str(published_build.home)},
    )
    get_settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert "published 14 tables" in result.output
    assert (out / "ecuador-lakehouse-1.0.0" / "manifest.json").is_file()


def test_example_imports_nothing_from_the_package() -> None:
    tree = ast.parse(EXAMPLE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert "ecuador_lakehouse" not in imported
    assert all(
        name == "duckdb" or name.split(".")[0] in sys.stdlib_module_names for name in imported
    )


def test_example_consumes_the_artifact(published_build: PublishedBuild) -> None:
    completed = subprocess.run(
        [sys.executable, str(EXAMPLE), str(published_build.artifact)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Latest tax year: 2026" in completed.stdout
    assert "1. " in completed.stdout
    assert "SRI/GDP" in completed.stdout


def test_manifest_is_valid_against_the_committed_schema(
    published_build: PublishedBuild,
) -> None:
    schema = json.loads(Path("docs/schemas/manifest.schema.json").read_text(encoding="utf-8"))
    manifest = json.loads((published_build.artifact / "manifest.json").read_text(encoding="utf-8"))

    jsonschema.validate(instance=manifest, schema=schema)
    assert manifest["quality"]["tests_total"] > 0
    assert manifest["quality"]["unit_tests_total"] > 0
