"""Tests for the published artifact contract and its semver diff rules (S14)."""

from __future__ import annotations

from importlib import resources

import pytest

from ecuador_lakehouse.domain.contract import (
    ArtifactContract,
    ContractColumn,
    ContractDiff,
    ContractTable,
    diff_contracts,
)
from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.manifest import ArtifactVersion


def _table(name: str, *columns: tuple[str, str], kind: str = "dim") -> ContractTable:
    return ContractTable(
        name=name,
        kind=kind,
        grain="grain",
        columns=tuple(ContractColumn(name=column, type=type_) for column, type_ in columns),
    )


def _contract(*tables: ContractTable, version: str = "1.0.0") -> ArtifactContract:
    return ArtifactContract(
        contract_version=ArtifactVersion.parse(version),
        artifact_name="ecuador-lakehouse",
        tables=tables or (_table("dim_date", ("month_key", "INTEGER")),),
    )


def test_packaged_contract_covers_the_fourteen_published_tables() -> None:
    text = (
        resources.files("ecuador_lakehouse")
        .joinpath("artifact_contract.json")
        .read_text(encoding="utf-8")
    )
    contract = ArtifactContract.from_json_text(text)

    assert str(contract.contract_version) == "1.0.0"
    assert contract.artifact_name == "ecuador-lakehouse"
    assert len(contract.tables) == 14
    kinds = [table.kind for table in contract.tables]
    assert kinds.count("dim") == 7
    assert kinds.count("fct") == 3
    assert kinds.count("mart") == 4
    assert {table.name for table in contract.tables} == {
        "dim_cpi_item",
        "dim_date",
        "dim_geography",
        "dim_national_account_item",
        "dim_price_area",
        "dim_quarter",
        "dim_tax_item",
        "fct_cpi_index",
        "fct_national_accounts",
        "fct_tax_collection",
        "mart_inflation_monthly",
        "mart_tax_collection_monthly",
        "mart_tax_lifecycle",
        "mart_tax_to_gdp_annual",
    }
    for table in contract.tables:
        assert table.grain
        assert table.columns


def test_contract_round_trips_through_its_deterministic_codec() -> None:
    contract = _contract(_table("dim_date", ("month_key", "INTEGER"), ("year", "INTEGER")))

    text = contract.to_json_text()

    assert text.endswith("\n")
    assert ArtifactContract.from_json_text(text) == contract
    assert contract.to_json_text() == text


def test_contract_rejects_duplicate_tables_and_columns() -> None:
    with pytest.raises(ConfigError, match="duplicate"):
        _contract(
            _table("dim_date", ("month_key", "INTEGER")),
            _table("dim_date", ("month_key", "INTEGER")),
        )
    with pytest.raises(ConfigError, match="duplicate"):
        _table("dim_date", ("month_key", "INTEGER"), ("month_key", "INTEGER"))


def test_identical_contracts_require_no_bump() -> None:
    diff = diff_contracts(_contract(), _contract())

    assert diff == ContractDiff()
    assert diff.required_bump == "none"


def test_removing_a_table_is_breaking_and_requires_a_major_bump() -> None:
    committed = _contract(
        _table("dim_date", ("month_key", "INTEGER")),
        _table("dim_quarter", ("quarter_key", "VARCHAR")),
    )
    current = _contract(_table("dim_date", ("month_key", "INTEGER")))

    diff = diff_contracts(committed, current)

    assert diff.breaking == ("table dim_quarter removed",)
    assert diff.additive == ()
    assert diff.required_bump == "major"


def test_removing_a_column_is_breaking_and_names_it() -> None:
    committed = _contract(_table("dim_date", ("month_key", "INTEGER"), ("year", "INTEGER")))
    current = _contract(_table("dim_date", ("month_key", "INTEGER")))

    diff = diff_contracts(committed, current)

    assert diff.breaking == ("dim_date.year removed",)
    assert diff.required_bump == "major"


def test_changing_a_column_type_is_breaking() -> None:
    committed = _contract(_table("dim_date", ("month_key", "INTEGER")))
    current = _contract(_table("dim_date", ("month_key", "BIGINT")))

    diff = diff_contracts(committed, current)

    assert diff.breaking == ("dim_date.month_key type changed from INTEGER to BIGINT",)
    assert diff.required_bump == "major"


def test_renaming_a_table_or_column_is_breaking() -> None:
    committed = _contract(_table("dim_date", ("month_key", "INTEGER")))
    current = _contract(_table("dim_month", ("month_key", "INTEGER")))

    diff = diff_contracts(committed, current)

    assert "table dim_date removed" in diff.breaking
    assert "table dim_month added" in diff.additive
    assert diff.required_bump == "major"


def test_adding_a_table_or_column_is_additive_and_requires_a_minor_bump() -> None:
    committed = _contract(_table("dim_date", ("month_key", "INTEGER")))
    current = _contract(
        _table("dim_date", ("month_key", "INTEGER"), ("year", "INTEGER")),
        _table("mart_extra", ("value", "DOUBLE"), kind="mart"),
    )

    diff = diff_contracts(committed, current)

    assert diff.breaking == ()
    assert diff.additive == ("dim_date.year added", "table mart_extra added")
    assert diff.required_bump == "minor"


def test_contract_version_must_be_semver() -> None:
    payload = _contract().to_json_text().replace('"1.0.0"', '"1.0"')

    with pytest.raises(ConfigError):
        ArtifactContract.from_json_text(payload)
