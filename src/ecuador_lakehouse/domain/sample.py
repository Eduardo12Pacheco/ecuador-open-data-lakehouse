"""Value objects and codec for the bundled offline sample (S3).

The sample manifest is the contract between the maintainer command that builds
the sample, the fetcher that reads it at runtime and ``lakehouse doctor``. It
is data, so the codec lives in the pure domain and produces deterministic JSON.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sources import SourceId

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_KEYS = frozenset({"schema_version", "builder_version", "checked_at", "files"})
_SAMPLE_FILE_KEYS = frozenset(
    {
        "name",
        "source_id",
        "partition",
        "bytes",
        "sha256",
        "rows",
        "derived_from_sha256",
    }
)
_REQUIRED_SAMPLE_FILE_KEYS = _SAMPLE_FILE_KEYS
CONTROL_TOTALS_COLUMNS = (
    "source_id",
    "period_year",
    "expected_total_usd",
    "is_frozen",
    "as_of_date",
)


def _is_plain_name(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and ".." not in value


@dataclass(frozen=True, slots=True)
class SampleFile:
    """One file inside ``sample_data/`` with its integrity metadata."""

    name: str
    source_id: SourceId
    partition: str
    size_bytes: int
    sha256: str
    rows: int
    derived_from_sha256: str

    def __post_init__(self) -> None:
        if not _is_plain_name(self.name):
            raise ValueError(f"name must be a plain file name: {self.name!r}")
        if not str(self.partition).strip():
            raise ValueError("partition must not be empty")
        if self.size_bytes < 0:
            raise ValueError(f"size_bytes must be non-negative: {self.size_bytes!r}")
        if self.rows < 0:
            raise ValueError(f"rows must be non-negative: {self.rows!r}")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError(f"sha256 must be 64 lowercase hex characters: {self.sha256!r}")
        if not _SHA256.fullmatch(self.derived_from_sha256):
            raise ValueError(
                "derived_from_sha256 must be 64 lowercase hex characters: "
                f"{self.derived_from_sha256!r}"
            )


@dataclass(frozen=True, slots=True)
class SampleManifest:
    """The complete bundled sample inventory, sorted by file name."""

    builder_version: str
    checked_at: str
    files: tuple[SampleFile, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        files = tuple(sorted(self.files, key=lambda entry: entry.name))
        object.__setattr__(self, "files", files)
        if self.schema_version != 1:
            raise ConfigError(
                f"unsupported sample manifest schema_version: {self.schema_version!r}"
            )
        if not self.builder_version.strip():
            raise ConfigError("sample manifest builder_version must not be empty")
        if not self.checked_at:
            raise ConfigError("sample manifest checked_at must not be empty")
        try:
            date.fromisoformat(self.checked_at)
        except ValueError as exc:
            raise ConfigError(
                f"sample manifest checked_at must be an ISO date (YYYY-MM-DD): {self.checked_at!r}"
            ) from exc
        if not files:
            raise ConfigError("sample manifest must contain at least one file")
        seen: set[str] = set()
        for entry in files:
            if entry.name in seen:
                raise ConfigError(f"sample manifest has a duplicate file name: {entry.name!r}")
            seen.add(entry.name)

    @property
    def total_bytes(self) -> int:
        """Total size of the bundled sample in bytes."""
        return sum(entry.size_bytes for entry in self.files)

    def find(self, name: str) -> SampleFile | None:
        """Return the manifest entry for ``name``, if present."""
        for entry in self.files:
            if entry.name == name:
                return entry
        return None

    def by_source(self, source_id: SourceId) -> tuple[SampleFile, ...]:
        """Return every bundled file belonging to one source."""
        return tuple(entry for entry in self.files if entry.source_id is source_id)

    def to_json_text(self) -> str:
        """Serialize the manifest deterministically (two-space indent, newline)."""
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "builder_version": self.builder_version,
            "checked_at": self.checked_at,
            "files": [self._file_to_dict(entry) for entry in self.files],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json_text(cls, text: str) -> SampleManifest:
        """Parse and validate manifest JSON, raising :class:`ConfigError` on bad input."""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"sample manifest is not valid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ConfigError("sample manifest must be a JSON object")
        unknown = set(payload) - _MANIFEST_KEYS
        if unknown:
            raise ConfigError(f"sample manifest has unknown keys: {', '.join(sorted(unknown))}")
        raw_files = payload.get("files")
        if not isinstance(raw_files, list):
            raise ConfigError("sample manifest must contain a 'files' list")
        builder_version = payload.get("builder_version", "")
        checked_at = payload.get("checked_at", "")
        if not isinstance(builder_version, str):
            raise ConfigError("sample manifest builder_version must be a string")
        if not isinstance(checked_at, str):
            raise ConfigError("sample manifest checked_at must be a string")
        schema_version = payload.get("schema_version", 1)
        if not isinstance(schema_version, int) or isinstance(schema_version, bool):
            raise ConfigError("sample manifest schema_version must be an integer")
        try:
            files = tuple(cls._file_from_dict(raw) for raw in raw_files)
        except ValueError as exc:
            raise ConfigError(f"invalid sample manifest entry: {exc}") from exc
        return cls(
            builder_version=builder_version,
            checked_at=checked_at,
            files=files,
            schema_version=schema_version,
        )

    @staticmethod
    def _file_to_dict(entry: SampleFile) -> dict[str, Any]:
        return {
            "name": entry.name,
            "source_id": entry.source_id.value,
            "partition": entry.partition,
            "bytes": entry.size_bytes,
            "sha256": entry.sha256,
            "rows": entry.rows,
            "derived_from_sha256": entry.derived_from_sha256,
        }

    @staticmethod
    def _file_from_dict(raw: object) -> SampleFile:
        if not isinstance(raw, dict):
            raise ConfigError("each sample manifest 'files' entry must be an object")
        unknown = set(raw) - _SAMPLE_FILE_KEYS
        if unknown:
            raise ConfigError(
                f"sample manifest file entry has unknown keys: {', '.join(sorted(unknown))}"
            )
        missing = _REQUIRED_SAMPLE_FILE_KEYS - set(raw)
        if missing:
            raise ConfigError(
                f"sample manifest file entry is missing keys: {', '.join(sorted(missing))}"
            )
        try:
            source_id = SourceId(raw["source_id"])
        except ValueError as exc:
            raise ConfigError(
                f"unknown source_id in sample manifest: {raw['source_id']!r}"
            ) from exc
        name = raw["name"]
        partition = raw["partition"]
        size_bytes = raw["bytes"]
        sha256 = raw["sha256"]
        rows = raw["rows"]
        derived_from = raw["derived_from_sha256"]
        for field_name, value in (
            ("name", name),
            ("partition", partition),
            ("sha256", sha256),
            ("derived_from_sha256", derived_from),
        ):
            if not isinstance(value, str):
                raise ConfigError(f"sample manifest {field_name} must be a string")
        for field_name, value in (("bytes", size_bytes), ("rows", rows)):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ConfigError(f"sample manifest {field_name} must be an integer")
        return SampleFile(
            name=name,
            source_id=source_id,
            partition=partition,
            size_bytes=size_bytes,
            sha256=sha256,
            rows=rows,
            derived_from_sha256=derived_from,
        )


@dataclass(frozen=True, slots=True)
class ControlTotal:
    """Control total of one source year used by dbt reconciliation tests."""

    source_id: SourceId
    period_year: int
    expected_total_usd: Decimal
    is_frozen: bool
    as_of_date: str

    def __post_init__(self) -> None:
        if self.period_year <= 0:
            raise ValueError(f"period_year must be positive: {self.period_year!r}")
        if not isinstance(self.expected_total_usd, Decimal):
            raise ValueError("expected_total_usd must be a Decimal")
        if not self.expected_total_usd.is_finite():
            raise ValueError(f"expected_total_usd must be finite: {self.expected_total_usd!r}")
        if not self.as_of_date:
            raise ValueError("as_of_date must not be empty")
        try:
            date.fromisoformat(self.as_of_date)
        except ValueError as exc:
            raise ValueError(f"as_of_date must be an ISO date: {self.as_of_date!r}") from exc


@dataclass(frozen=True, slots=True)
class SampleBuildReport:
    """Outcome of one ``lakehouse sample build`` run (maintainer command)."""

    files: tuple[SampleFile, ...] = ()
    control_totals: tuple[ControlTotal, ...] = field(default_factory=tuple)

    @property
    def total_bytes(self) -> int:
        """Total size of the regenerated sample in bytes."""
        return sum(entry.size_bytes for entry in self.files)
