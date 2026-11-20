"""Documentation coverage of the dbt project (S7, T9)."""

from __future__ import annotations

from typing import Any

from .conftest import StagingBuild


def _models(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        node
        for node in manifest["nodes"].values()
        if node.get("resource_type") == "model" and node.get("package_name") == "ecuador_lakehouse"
    ]


def test_every_model_and_column_has_a_description(marts_build: StagingBuild) -> None:
    manifest = dict(marts_build.transformer.manifest())

    missing: list[str] = []
    for model in _models(manifest):
        if not str(model.get("description", "")).strip():
            missing.append(model["name"])
        for column in model.get("columns", {}).values():
            if not str(column.get("description", "")).strip():
                missing.append(f"{model['name']}.{column.get('name', '?')}")

    assert missing == []


def test_every_mart_enforces_its_contract(marts_build: StagingBuild) -> None:
    manifest = dict(marts_build.transformer.manifest())

    marts = [
        model
        for model in _models(manifest)
        if str(model.get("original_file_path", "")).replace("\\", "/").startswith("models/marts/")
    ]

    assert len(marts) == 14
    not_enforced = [
        model["name"]
        for model in marts
        if not model.get("config", {}).get("contract", {}).get("enforced", False)
    ]
    assert not_enforced == []


def test_the_analytic_marts_are_documented(marts_build: StagingBuild) -> None:
    manifest = dict(marts_build.transformer.manifest())
    documented = {model["name"] for model in _models(manifest)}

    assert {
        "mart_tax_collection_monthly",
        "mart_inflation_monthly",
        "mart_tax_to_gdp_annual",
        "mart_tax_lifecycle",
    } <= documented
