"""The committed artifact contract and its semver diff rules (S14, ADR 0007).

The contract is the public schema of the published data product: every table,
its kind, grain and typed columns. Comparing the committed contract with the
schema actually materialized in the warehouse yields a :class:`ContractDiff`:
removals and type changes are breaking (MAJOR bump), additions are additive
(MINOR bump). The codec is pure and deterministic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Self

from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.manifest import ArtifactVersion

CONTRACT_SCHEMA_VERSION = 1
_KINDS = frozenset({"dim", "fct", "mart"})
_CONTRACT_KEYS = frozenset({"schema_version", "contract_version", "artifact_name", "tables"})
_TABLE_KEYS = frozenset({"name", "kind", "grain", "columns"})
_COLUMN_KEYS = frozenset({"name", "type"})


def _plain_name(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and ".." not in value


@dataclass(frozen=True, slots=True)
class ContractColumn:
    """One typed column of a published table."""

    name: str
    type: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("contract column name must not be empty")
        if not self.type.strip():
            raise ValueError(f"contract column {self.name!r} must have a type")


@dataclass(frozen=True, slots=True)
class ContractTable:
    """One published table with its kind, grain and typed columns."""

    name: str
    kind: str
    grain: str
    columns: tuple[ContractColumn, ...] = ()

    def __post_init__(self) -> None:
        if not _plain_name(self.name):
            raise ConfigError(f"contract table name must be a plain name: {self.name!r}")
        if self.kind not in _KINDS:
            raise ConfigError(f"contract table {self.name!r} has unknown kind: {self.kind!r}")
        if not self.grain.strip():
            raise ConfigError(f"contract table {self.name!r} must declare a grain")
        columns = tuple(self.columns)
        object.__setattr__(self, "columns", columns)
        if not columns:
            raise ConfigError(f"contract table {self.name!r} must have at least one column")
        seen: set[str] = set()
        for column in columns:
            if column.name in seen:
                raise ConfigError(
                    f"contract table {self.name!r} has a duplicate column: {column.name!r}"
                )
            seen.add(column.name)


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    """The complete public contract of the data product."""

    contract_version: ArtifactVersion
    artifact_name: str
    tables: tuple[ContractTable, ...] = ()
    schema_version: int = CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        tables = tuple(sorted(self.tables, key=lambda table: table.name))
        object.__setattr__(self, "tables", tables)
        if self.schema_version != CONTRACT_SCHEMA_VERSION:
            raise ConfigError(
                f"unsupported artifact contract schema_version: {self.schema_version!r}"
            )
        if not self.artifact_name.strip():
            raise ConfigError("artifact contract name must not be empty")
        if not tables:
            raise ConfigError("artifact contract must contain at least one table")
        seen: set[str] = set()
        for table in tables:
            if table.name in seen:
                raise ConfigError(f"artifact contract has a duplicate table: {table.name!r}")
            seen.add(table.name)

    def find_table(self, name: str) -> ContractTable | None:
        """Return the table named ``name``, if the contract covers it."""
        for table in self.tables:
            if table.name == name:
                return table
        return None

    def to_json_text(self) -> str:
        """Serialize deterministically (explicit field order, two-space indent)."""
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "contract_version": str(self.contract_version),
            "artifact_name": self.artifact_name,
            "tables": [
                {
                    "name": table.name,
                    "kind": table.kind,
                    "grain": table.grain,
                    "columns": [
                        {"name": column.name, "type": column.type} for column in table.columns
                    ],
                }
                for table in self.tables
            ],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json_text(cls, text: str) -> Self:
        """Parse and validate contract JSON, raising :class:`ConfigError` on bad input."""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"artifact contract is not valid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ConfigError("artifact contract must be a JSON object")
        unknown = set(payload) - _CONTRACT_KEYS
        if unknown:
            raise ConfigError(f"artifact contract has unknown keys: {', '.join(sorted(unknown))}")
        missing = _CONTRACT_KEYS - set(payload)
        if missing:
            raise ConfigError(f"artifact contract is missing keys: {', '.join(sorted(missing))}")
        schema_version = payload["schema_version"]
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise ConfigError("artifact contract schema_version must be an integer")
        tables_raw = payload["tables"]
        if not isinstance(tables_raw, list):
            raise ConfigError("artifact contract tables must be a list")
        try:
            return cls(
                contract_version=ArtifactVersion.parse(_string(payload, "contract_version")),
                artifact_name=_string(payload, "artifact_name"),
                tables=tuple(_table_from_dict(raw) for raw in tables_raw),
                schema_version=schema_version,
            )
        except ValueError as exc:
            raise ConfigError(f"invalid artifact contract: {exc}") from exc


@dataclass(frozen=True, slots=True)
class ContractDiff:
    """Breaking and additive differences between two contracts."""

    breaking: tuple[str, ...] = ()
    additive: tuple[str, ...] = ()

    @property
    def required_bump(self) -> Literal["major", "minor", "none"]:
        """Semver bump the current contract needs to represent this diff."""
        if self.breaking:
            return "major"
        if self.additive:
            return "minor"
        return "none"


def diff_contracts(committed: ArtifactContract, current: ArtifactContract) -> ContractDiff:
    """Compare the committed contract with the contract read from the warehouse."""
    committed_tables = {table.name: table for table in committed.tables}
    current_tables = {table.name: table for table in current.tables}
    breaking: list[str] = []
    additive: list[str] = []
    for table in committed.tables:
        if table.name not in current_tables:
            breaking.append(f"table {table.name} removed")
            continue
        current_columns = {column.name: column for column in current_tables[table.name].columns}
        for column in table.columns:
            replacement = current_columns.get(column.name)
            if replacement is None:
                breaking.append(f"{table.name}.{column.name} removed")
            elif replacement.type != column.type:
                breaking.append(
                    f"{table.name}.{column.name} type changed "
                    f"from {column.type} to {replacement.type}"
                )
    for table in current.tables:
        if table.name not in committed_tables:
            additive.append(f"table {table.name} added")
            continue
        committed_columns = {column.name for column in committed_tables[table.name].columns}
        for column in table.columns:
            if column.name not in committed_columns:
                additive.append(f"{table.name}.{column.name} added")
    return ContractDiff(breaking=tuple(breaking), additive=tuple(additive))


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"artifact contract {key} must be a string")
    return value


def _table_from_dict(raw: object) -> ContractTable:
    if not isinstance(raw, dict):
        raise ConfigError("each artifact contract table must be an object")
    unknown = set(raw) - _TABLE_KEYS
    if unknown:
        raise ConfigError(f"artifact contract table has unknown keys: {', '.join(sorted(unknown))}")
    missing = _TABLE_KEYS - set(raw)
    if missing:
        raise ConfigError(f"artifact contract table is missing keys: {', '.join(sorted(missing))}")
    columns_raw = raw["columns"]
    if not isinstance(columns_raw, list):
        raise ConfigError("artifact contract columns must be a list")
    try:
        return ContractTable(
            name=_string(raw, "name"),
            kind=_string(raw, "kind"),
            grain=_string(raw, "grain"),
            columns=tuple(_column_from_dict(column) for column in columns_raw),
        )
    except ValueError as exc:
        raise ConfigError(f"invalid artifact contract table: {exc}") from exc


def _column_from_dict(raw: object) -> ContractColumn:
    if not isinstance(raw, dict):
        raise ConfigError("each artifact contract column must be an object")
    unknown = set(raw) - _COLUMN_KEYS
    if unknown:
        raise ConfigError(
            f"artifact contract column has unknown keys: {', '.join(sorted(unknown))}"
        )
    missing = _COLUMN_KEYS - set(raw)
    if missing:
        raise ConfigError(f"artifact contract column is missing keys: {', '.join(sorted(missing))}")
    try:
        return ContractColumn(name=_string(raw, "name"), type=_string(raw, "type"))
    except ValueError as exc:
        raise ConfigError(f"invalid artifact contract column: {exc}") from exc
