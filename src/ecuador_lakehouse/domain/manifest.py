"""Value objects and the deterministic codec for the published artifact (S14, D19).

The manifest is the machine-readable description of one published artifact: its
contract version, the pinned sources it was built from, every table with its
grain, columns, row count and logical content fingerprint, and the quality-gate
counts observed before publishing. It deliberately contains no wall-clock fields
so two builds from the same inputs produce the same document (S15).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Self

from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sources import SourceId

SCHEMA_VERSION = "1.0"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_MODES = frozenset({"sample", "full"})
_KINDS = frozenset({"dim", "fct", "mart"})
_BUMP_KINDS = frozenset({"major", "minor", "patch"})

_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "artifact_name",
        "artifact_version",
        "generator",
        "duckdb_version",
        "dbt_core_version",
        "data_mode",
        "built_from",
        "tables",
        "quality",
        "attribution",
    }
)
_TABLE_KEYS = frozenset(
    {
        "name",
        "schema",
        "kind",
        "grain",
        "row_count",
        "columns",
        "content_sha256",
        "parquet_file",
    }
)
_COLUMN_KEYS = frozenset({"name", "type", "description"})
_SOURCE_KEYS = frozenset({"source_id", "url", "license_id", "files"})
_FILE_KEYS = frozenset({"name", "sha256"})
_QUALITY_KEYS = frozenset({"tests_total", "tests_passed", "unit_tests_total", "unit_tests_passed"})


@dataclass(frozen=True, slots=True, order=True)
class ArtifactVersion:
    """A semantic version with explicit bump operations."""

    major: int
    minor: int
    patch: int

    def __post_init__(self) -> None:
        for name, value in (("major", self.major), ("minor", self.minor), ("patch", self.patch)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer: {value!r}")

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @classmethod
    def parse(cls, text: str) -> Self:
        """Parse ``MAJOR.MINOR.PATCH``, raising :class:`ConfigError` on bad input."""
        if not isinstance(text, str) or not text.strip():
            raise ConfigError("artifact version must be a non-empty semver string")
        match = _SEMVER.fullmatch(text.strip())
        if match is None:
            raise ConfigError(f"artifact version must be MAJOR.MINOR.PATCH: {text!r}")
        return cls(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    def bump(self, kind: Literal["major", "minor", "patch"]) -> ArtifactVersion:
        """Return the next version for a breaking, additive or fix-only change."""
        if kind not in _BUMP_KINDS:
            raise ValueError(f"unknown version bump: {kind!r}")
        if kind == "major":
            return ArtifactVersion(self.major + 1, 0, 0)
        if kind == "minor":
            return ArtifactVersion(self.major, self.minor + 1, 0)
        return ArtifactVersion(self.major, self.minor, self.patch + 1)


def _plain_name(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and ".." not in value


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    """One published column with its logical type and dbt description."""

    name: str
    type: str
    description: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("column name must not be empty")
        if not self.type.strip():
            raise ValueError(f"column {self.name!r} must have a type")
        if not self.description.strip():
            raise ValueError(f"column {self.name!r} must have a description")


@dataclass(frozen=True, slots=True)
class FileRef:
    """One input file recorded for provenance."""

    name: str
    sha256: str

    def __post_init__(self) -> None:
        if not _plain_name(self.name):
            raise ValueError(f"file name must be a plain file name: {self.name!r}")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError(f"file sha256 must be 64 lowercase hex characters: {self.sha256!r}")


@dataclass(frozen=True, slots=True)
class SourceRef:
    """One upstream source and the exact files that fed the artifact."""

    source_id: SourceId
    url: str
    license_id: str
    files: tuple[FileRef, ...] = ()

    def __post_init__(self) -> None:
        files = tuple(sorted(self.files, key=lambda entry: entry.name))
        object.__setattr__(self, "files", files)
        if not self.url.strip():
            raise ValueError(f"source {self.source_id.value!r} must have a URL")
        if not self.license_id.strip():
            raise ValueError(f"source {self.source_id.value!r} must have a license id")
        seen: set[str] = set()
        for entry in files:
            if entry.name in seen:
                raise ValueError(
                    f"source {self.source_id.value!r} has a duplicate file: {entry.name!r}"
                )
            seen.add(entry.name)


@dataclass(frozen=True, slots=True)
class QualityCounts:
    """Quality-gate counts observed immediately before publishing."""

    tests_total: int
    tests_passed: int
    unit_tests_total: int
    unit_tests_passed: int

    def __post_init__(self) -> None:
        pairs = (
            ("tests", self.tests_total, self.tests_passed),
            ("unit_tests", self.unit_tests_total, self.unit_tests_passed),
        )
        for label, total, passed in pairs:
            for field_name, value in ((f"{label}_total", total), (f"{label}_passed", passed)):
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ValueError(f"{field_name} must be a non-negative integer: {value!r}")
            if passed > total:
                raise ValueError(f"{label}_passed must not exceed {label}_total")


@dataclass(frozen=True, slots=True)
class TableInfo:
    """One table in the artifact: schema, grain, columns, rows and fingerprint."""

    name: str
    kind: str
    grain: str
    row_count: int
    columns: tuple[ColumnInfo, ...]
    content_sha256: str
    parquet_file: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("table name must not be empty")
        if self.kind not in _KINDS:
            raise ValueError(f"table {self.name!r} has unknown kind: {self.kind!r}")
        if not self.grain.strip():
            raise ValueError(f"table {self.name!r} must declare a grain")
        if not isinstance(self.row_count, int) or isinstance(self.row_count, bool):
            raise ValueError(f"table {self.name!r} row_count must be an integer")
        if self.row_count < 0:
            raise ValueError(f"table {self.name!r} row_count must be non-negative")
        columns = tuple(self.columns)
        object.__setattr__(self, "columns", columns)
        if not columns:
            raise ValueError(f"table {self.name!r} must have at least one column")
        seen: set[str] = set()
        for column in columns:
            if column.name in seen:
                raise ValueError(f"table {self.name!r} has a duplicate column: {column.name!r}")
            seen.add(column.name)
        if not _SHA256.fullmatch(self.content_sha256):
            raise ValueError(
                f"table {self.name!r} content_sha256 must be 64 lowercase hex characters"
            )
        expected = f"parquet/{self.name}.parquet"
        if self.parquet_file != expected:
            raise ValueError(
                f"table {self.name!r} parquet_file must be {expected!r}: {self.parquet_file!r}"
            )


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """The complete, deterministic description of one published artifact."""

    artifact_name: str
    artifact_version: ArtifactVersion
    generator: str
    duckdb_version: str
    dbt_core_version: str
    data_mode: str
    built_from: tuple[SourceRef, ...]
    tables: tuple[TableInfo, ...]
    quality: QualityCounts
    attribution: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ConfigError(
                f"unsupported artifact manifest schema_version: {self.schema_version!r}"
            )
        for field_name, value in (
            ("artifact_name", self.artifact_name),
            ("generator", self.generator),
            ("duckdb_version", self.duckdb_version),
            ("dbt_core_version", self.dbt_core_version),
            ("attribution", self.attribution),
        ):
            if not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        if self.data_mode not in _MODES:
            raise ValueError(f"data_mode must be one of {sorted(_MODES)}: {self.data_mode!r}")
        tables = tuple(sorted(self.tables, key=lambda table: table.name))
        object.__setattr__(self, "tables", tables)
        if not tables:
            raise ConfigError("artifact manifest must contain at least one table")
        seen: set[str] = set()
        for table in tables:
            if table.name in seen:
                raise ConfigError(f"artifact manifest has a duplicate table: {table.name!r}")
            seen.add(table.name)
        sources = tuple(sorted(self.built_from, key=lambda source: source.source_id.value))
        object.__setattr__(self, "built_from", sources)
        if not sources:
            raise ConfigError("artifact manifest must record at least one source")
        if len({source.source_id for source in sources}) != len(sources):
            raise ConfigError("artifact manifest has duplicate sources")

    def find_table(self, name: str) -> TableInfo | None:
        """Return the table named ``name``, if the artifact contains it."""
        for table in self.tables:
            if table.name == name:
                return table
        return None

    def to_json_text(self) -> str:
        """Serialize deterministically (explicit field order, two-space indent)."""
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "artifact_name": self.artifact_name,
            "artifact_version": str(self.artifact_version),
            "generator": self.generator,
            "duckdb_version": self.duckdb_version,
            "dbt_core_version": self.dbt_core_version,
            "data_mode": self.data_mode,
            "built_from": [
                {
                    "source_id": source.source_id.value,
                    "url": source.url,
                    "license_id": source.license_id,
                    "files": [
                        {"name": entry.name, "sha256": entry.sha256} for entry in source.files
                    ],
                }
                for source in self.built_from
            ],
            "tables": [
                {
                    "name": table.name,
                    "schema": "marts",
                    "kind": table.kind,
                    "grain": table.grain,
                    "row_count": table.row_count,
                    "columns": [
                        {
                            "name": column.name,
                            "type": column.type,
                            "description": column.description,
                        }
                        for column in table.columns
                    ],
                    "content_sha256": table.content_sha256,
                    "parquet_file": table.parquet_file,
                }
                for table in self.tables
            ],
            "quality": {
                "tests_total": self.quality.tests_total,
                "tests_passed": self.quality.tests_passed,
                "unit_tests_total": self.quality.unit_tests_total,
                "unit_tests_passed": self.quality.unit_tests_passed,
            },
            "attribution": self.attribution,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json_text(cls, text: str) -> Self:
        """Parse and validate manifest JSON, raising :class:`ConfigError` on bad input."""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"artifact manifest is not valid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ConfigError("artifact manifest must be a JSON object")
        _reject_unknown(payload, _MANIFEST_KEYS, "artifact manifest")
        missing = _MANIFEST_KEYS - set(payload)
        if missing:
            raise ConfigError(f"artifact manifest is missing keys: {', '.join(sorted(missing))}")
        try:
            return cls(
                schema_version=_string(payload, "schema_version"),
                artifact_name=_string(payload, "artifact_name"),
                artifact_version=ArtifactVersion.parse(_string(payload, "artifact_version")),
                generator=_string(payload, "generator"),
                duckdb_version=_string(payload, "duckdb_version"),
                dbt_core_version=_string(payload, "dbt_core_version"),
                data_mode=_string(payload, "data_mode"),
                built_from=tuple(_source_from_dict(raw) for raw in _list(payload, "built_from")),
                tables=tuple(_table_from_dict(raw) for raw in _list(payload, "tables")),
                quality=_quality_from_dict(payload["quality"]),
                attribution=_string(payload, "attribution"),
            )
        except ValueError as exc:
            raise ConfigError(f"invalid artifact manifest: {exc}") from exc


def _reject_unknown(payload: dict[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ConfigError(f"{label} has unknown keys: {', '.join(sorted(unknown))}")


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"artifact manifest {key} must be a string")
    return value


def _list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ConfigError(f"artifact manifest {key} must be a list")
    return value


def _table_from_dict(raw: object) -> TableInfo:
    if not isinstance(raw, dict):
        raise ConfigError("each artifact manifest table must be an object")
    _reject_unknown(raw, _TABLE_KEYS, "artifact manifest table")
    missing = _TABLE_KEYS - set(raw)
    if missing:
        raise ConfigError(f"artifact manifest table is missing keys: {', '.join(sorted(missing))}")
    schema = raw["schema"]
    if schema != "marts":
        raise ConfigError(f"artifact manifest tables must live in marts: {schema!r}")
    columns_raw = raw["columns"]
    if not isinstance(columns_raw, list):
        raise ConfigError("artifact manifest columns must be a list")
    try:
        return TableInfo(
            name=_required_str(raw, "name"),
            kind=_required_str(raw, "kind"),
            grain=_required_str(raw, "grain"),
            row_count=_required_int(raw, "row_count"),
            columns=tuple(_column_from_dict(column) for column in columns_raw),
            content_sha256=_required_str(raw, "content_sha256"),
            parquet_file=_required_str(raw, "parquet_file"),
        )
    except ConfigError:
        raise
    except ValueError as exc:
        raise ConfigError(f"invalid artifact manifest table: {exc}") from exc


def _column_from_dict(raw: object) -> ColumnInfo:
    if not isinstance(raw, dict):
        raise ConfigError("each artifact manifest column must be an object")
    _reject_unknown(raw, _COLUMN_KEYS, "artifact manifest column")
    missing = _COLUMN_KEYS - set(raw)
    if missing:
        raise ConfigError(f"artifact manifest column is missing keys: {', '.join(sorted(missing))}")
    try:
        return ColumnInfo(
            name=_required_str(raw, "name"),
            type=_required_str(raw, "type"),
            description=_required_str(raw, "description"),
        )
    except ValueError as exc:
        raise ConfigError(f"invalid artifact manifest column: {exc}") from exc


def _source_from_dict(raw: object) -> SourceRef:
    if not isinstance(raw, dict):
        raise ConfigError("each artifact manifest source must be an object")
    _reject_unknown(raw, _SOURCE_KEYS, "artifact manifest source")
    missing = _SOURCE_KEYS - set(raw)
    if missing:
        raise ConfigError(f"artifact manifest source is missing keys: {', '.join(sorted(missing))}")
    files_raw = raw["files"]
    if not isinstance(files_raw, list):
        raise ConfigError("artifact manifest source files must be a list")
    try:
        return SourceRef(
            source_id=SourceId(_required_str(raw, "source_id")),
            url=_required_str(raw, "url"),
            license_id=_required_str(raw, "license_id"),
            files=tuple(_file_from_dict(entry) for entry in files_raw),
        )
    except ValueError as exc:
        raise ConfigError(f"invalid artifact manifest source: {exc}") from exc


def _file_from_dict(raw: object) -> FileRef:
    if not isinstance(raw, dict):
        raise ConfigError("each artifact manifest file must be an object")
    _reject_unknown(raw, _FILE_KEYS, "artifact manifest file")
    missing = _FILE_KEYS - set(raw)
    if missing:
        raise ConfigError(f"artifact manifest file is missing keys: {', '.join(sorted(missing))}")
    try:
        return FileRef(name=_required_str(raw, "name"), sha256=_required_str(raw, "sha256"))
    except ValueError as exc:
        raise ConfigError(f"invalid artifact manifest file: {exc}") from exc


def _quality_from_dict(raw: object) -> QualityCounts:
    if not isinstance(raw, dict):
        raise ConfigError("artifact manifest quality must be an object")
    _reject_unknown(raw, _QUALITY_KEYS, "artifact manifest quality")
    missing = _QUALITY_KEYS - set(raw)
    if missing:
        raise ConfigError(
            f"artifact manifest quality is missing keys: {', '.join(sorted(missing))}"
        )
    try:
        return QualityCounts(
            tests_total=_required_int(raw, "tests_total"),
            tests_passed=_required_int(raw, "tests_passed"),
            unit_tests_total=_required_int(raw, "unit_tests_total"),
            unit_tests_passed=_required_int(raw, "unit_tests_passed"),
        )
    except ValueError as exc:
        raise ConfigError(f"invalid artifact manifest quality: {exc}") from exc


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"artifact manifest {key} must be a string")
    return value


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"artifact manifest {key} must be an integer")
    return value
