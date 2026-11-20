"""Publish dbt static documentation and the Mermaid lineage document (S12)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ecuador_lakehouse.application.ports import LineageRenderer, Transformer


@dataclass(frozen=True, slots=True)
class DocsResult:
    """Paths written by one documentation run."""

    site_index: Path
    mermaid_path: Path | None
    static_source: Path


class BuildDocs:
    """Use case that generates dbt docs and an optional Mermaid lineage file."""

    def __init__(
        self,
        *,
        transformer: Transformer,
        renderer: LineageRenderer,
        site_dir: Path,
    ) -> None:
        self._transformer = transformer
        self._renderer = renderer
        self._site_dir = Path(site_dir)

    def execute(self, *, mermaid_path: Path | None = None) -> DocsResult:
        """Generate static docs into the report site and optionally write lineage."""
        static_source = self._transformer.docs()
        site_index = self._site_dir / "lineage" / "index.html"
        site_index.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(static_source, site_index)

        written_mermaid: Path | None = None
        if mermaid_path is not None:
            document = self._renderer.render_markdown(self._transformer.manifest())
            written_mermaid = Path(mermaid_path)
            written_mermaid.parent.mkdir(parents=True, exist_ok=True)
            written_mermaid.write_text(document, encoding="utf-8")
        return DocsResult(
            site_index=site_index,
            mermaid_path=written_mermaid,
            static_source=static_source,
        )
