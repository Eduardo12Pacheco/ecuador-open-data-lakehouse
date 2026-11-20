"""Unit tests for the Mermaid lineage renderer (S12)."""

from __future__ import annotations

from typing import Any

from ecuador_lakehouse.adapters.docs.lineage_mermaid import (
    LineageMermaidRenderer,
    render_lineage_markdown,
    render_mermaid,
)


def model(unique_id: str, name: str, path: str, parents: list[str]) -> dict[str, Any]:
    """Build the subset of a manifest node used by the renderer."""
    return {
        "unique_id": unique_id,
        "name": name,
        "resource_type": "model",
        "package_name": "ecuador_lakehouse",
        "original_file_path": path,
        "depends_on": {"nodes": parents},
    }


def manifest(models: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap nodes in a minimal manifest payload."""
    return {"nodes": {node["unique_id"]: node for node in models}}


def test_renders_layers_edges_and_ignores_non_model_nodes() -> None:
    nodes = [
        model("model.p.stg", "stg", "models/staging/stg.sql", ["source.p.raw"]),
        model("model.p.int", "int", "models/intermediate/int.sql", ["model.p.stg"]),
        model("model.p.mart", "mart", "models/marts/analytics/mart.sql", ["model.p.int"]),
    ]
    nodes.append(
        {
            "unique_id": "source.p.raw",
            "name": "raw",
            "resource_type": "source",
            "package_name": "ecuador_lakehouse",
        }
    )

    mermaid = render_mermaid(manifest(nodes))

    assert "subgraph staging" in mermaid
    assert "subgraph intermediate" in mermaid
    assert "subgraph marts" in mermaid
    assert "stg --> int" in mermaid
    assert "int --> mart" in mermaid
    assert "raw" not in mermaid


def test_render_is_independent_of_manifest_insertion_order() -> None:
    nodes = [
        model("model.p.a", "a", "models/staging/a.sql", []),
        model("model.p.b", "b", "models/marts/b.sql", ["model.p.a"]),
        model("model.p.c", "c", "models/marts/c.sql", ["model.p.a", "model.p.b"]),
    ]

    assert render_mermaid(manifest(nodes)) == render_mermaid(manifest(list(reversed(nodes))))
    assert render_mermaid(manifest(nodes)).count("-->") == 3


def test_unknown_layers_are_grouped_last_and_markdown_has_a_header() -> None:
    nodes = [
        model("model.p.x", "x", "macros/x.sql", []),
        model("model.p.y", "y", "models/staging/y.sql", []),
    ]

    mermaid = render_mermaid(manifest(nodes))
    assert mermaid.index("subgraph staging") < mermaid.index("subgraph other")

    document = render_lineage_markdown(manifest(nodes))
    assert document.startswith("# dbt lineage")
    assert document.endswith("```\n")
    assert LineageMermaidRenderer().render_markdown(manifest(nodes)) == document
