"""Lineage documentation: committed mermaid graph and static dbt docs (S12, T9)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ecuador_lakehouse.adapters.docs.lineage_mermaid import render_lineage_markdown
from ecuador_lakehouse.cli.app import app

from .conftest import StagingBuild

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LINEAGE_PATH = PROJECT_ROOT / "docs" / "LINEAGE.md"


def test_committed_lineage_matches_a_fresh_dbt_parse(marts_build: StagingBuild) -> None:
    manifest = dict(marts_build.transformer.parse())

    expected = render_lineage_markdown(manifest)

    assert LINEAGE_PATH.read_text(encoding="utf-8") == expected


def test_lakehouse_docs_writes_static_docs_and_mermaid(
    marts_build: StagingBuild,
    tmp_path: Path,
    monkeypatch,
) -> None:
    mermaid_path = tmp_path / "LINEAGE.md"
    monkeypatch.setenv("LAKEHOUSE_HOME", str(marts_build.home))

    result = CliRunner().invoke(app, ["docs", "--mermaid", str(mermaid_path)])

    assert result.exit_code == 0, result.output
    static_index = marts_build.home / "site" / "lineage" / "index.html"
    assert static_index.is_file()
    assert static_index.stat().st_size > 0
    assert mermaid_path.read_text(encoding="utf-8").startswith("# dbt lineage")
    assert "flowchart LR" in mermaid_path.read_text(encoding="utf-8")
