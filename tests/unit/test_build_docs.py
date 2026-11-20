"""Unit tests for the documentation use case (S12)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ecuador_lakehouse.application.use_cases.build_docs import BuildDocs


class FakeTransformer:
    """Minimal ``Transformer`` test double for the docs use case."""

    def __init__(self, static_index: Path, manifest: Mapping[str, Any]) -> None:
        self.static_index = static_index
        self._manifest = manifest

    def docs(self) -> Path:
        return self.static_index

    def manifest(self) -> Mapping[str, Any]:
        return self._manifest


class FakeRenderer:
    """Deterministic renderer that records the manifest it received."""

    def __init__(self) -> None:
        self.received: Mapping[str, Any] | None = None

    def render_markdown(self, manifest: Mapping[str, Any]) -> str:
        self.received = manifest
        return "# lineage\n\n```mermaid\nflowchart LR\n```\n"


def test_copies_static_docs_into_the_site_and_writes_mermaid(tmp_path: Path) -> None:
    static_index = tmp_path / "target" / "static_index.html"
    static_index.parent.mkdir()
    static_index.write_text("<html>docs</html>", encoding="utf-8")
    renderer = FakeRenderer()
    use_case = BuildDocs(
        transformer=FakeTransformer(static_index, {"nodes": {}}),
        renderer=renderer,
        site_dir=tmp_path / "site",
    )

    result = use_case.execute(mermaid_path=tmp_path / "docs" / "LINEAGE.md")

    assert result.site_index == tmp_path / "site" / "lineage" / "index.html"
    assert result.site_index.read_text(encoding="utf-8") == "<html>docs</html>"
    assert result.static_source == static_index
    assert result.mermaid_path == tmp_path / "docs" / "LINEAGE.md"
    assert result.mermaid_path.read_text(encoding="utf-8").startswith("# lineage")
    assert renderer.received == {"nodes": {}}


def test_skips_the_markdown_when_no_path_is_given(tmp_path: Path) -> None:
    static_index = tmp_path / "static_index.html"
    static_index.write_text("<html></html>", encoding="utf-8")
    use_case = BuildDocs(
        transformer=FakeTransformer(static_index, {}),
        renderer=FakeRenderer(),
        site_dir=tmp_path / "site",
    )

    result = use_case.execute()

    assert result.mermaid_path is None
    assert result.site_index.is_file()
