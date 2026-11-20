"""Source inventory value objects and the pure ``sources.lock.json`` codec.

The lockfile is data, not configuration tied to the filesystem: decoding and
encoding live in the domain so the same rules apply to the bundled sample and
to downloaded files, and so tests can round-trip it without I/O.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from ecuador_lakehouse.domain.errors import ConfigError

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LOCKFILE_KEYS = frozenset({"schema_version", "checked_at", "licenses", "files"})
_SOURCE_FILE_KEYS = frozenset(
    {
        "source_id",
        "partition",
        "url",
        "filename",
        "size_bytes",
        "sha256",
        "mutable",
        "encoding_hint",
    }
)
_REQUIRED_SOURCE_FILE_KEYS = frozenset(
    {"source_id", "partition", "url", "filename", "size_bytes", "sha256"}
)


class SourceId(StrEnum):
    """Stable identifiers for the three verified upstream sources."""

    SRI_TAX = "sri_tax"
    BCE_CNT = "bce_cnt"
    INEC_CPI = "inec_cpi"


@dataclass(frozen=True, slots=True)
class LicenseInfo:
    """License metadata reported by the CKAN catalogue or the source page."""

    license_id: str
    title: str = ""
    url: str = ""

    def __post_init__(self) -> None:
        if not self.license_id.strip():
            raise ValueError("license_id must not be empty")


@dataclass(frozen=True, slots=True)
class SourceFile:
    """One pinned upstream file and everything needed to fetch and verify it."""

    source_id: SourceId
    partition: str
    url: str
    filename: str
    size_bytes: int
    sha256: str
    mutable: bool = False
    encoding_hint: str | None = None

    def __post_init__(self) -> None:
        if not str(self.partition).strip():
            raise ValueError("partition must not be empty")
        if not self.url.strip():
            raise ValueError("url must not be empty")
        if (
            not self.filename.strip()
            or "/" in self.filename
            or "\\" in self.filename
            or "\x00" in self.filename
            or ".." in self.filename
        ):
            raise ValueError(f"filename must be a plain file name: {self.filename!r}")
        if self.size_bytes < 0:
            raise ValueError(f"size_bytes must be non-negative: {self.size_bytes!r}")
        if not _SHA256.fullmatch(self.sha256):
            raise ValueError(f"sha256 must be 64 lowercase hex characters: {self.sha256!r}")
        if self.encoding_hint is not None and not self.encoding_hint.strip():
            raise ValueError("encoding_hint must be None or non-empty")


@dataclass(frozen=True, slots=True)
class Lockfile:
    """The complete pinned source inventory with its license metadata."""

    files: tuple[SourceFile, ...] = ()
    checked_at: str = ""
    licenses: dict[str, str] = field(default_factory=dict)
    schema_version: int = 1

    def __post_init__(self) -> None:
        files = tuple(self.files)
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "licenses", dict(self.licenses))
        if self.schema_version != 1:
            raise ConfigError(f"unsupported lockfile schema_version: {self.schema_version!r}")
        if self.checked_at:
            try:
                date.fromisoformat(self.checked_at)
            except ValueError as exc:
                raise ConfigError(
                    f"lockfile checked_at must be an ISO date (YYYY-MM-DD): {self.checked_at!r}"
                ) from exc
        seen: set[tuple[SourceId, str]] = set()
        for source_file in files:
            key = (source_file.source_id, source_file.partition)
            if key in seen:
                raise ConfigError(
                    "duplicate lockfile entry for "
                    f"{source_file.source_id.value}/{source_file.partition}"
                )
            seen.add(key)

    def find(self, source_id: SourceId, partition: str) -> SourceFile | None:
        """Return the pinned file for a source partition, if present."""
        for source_file in self.files:
            if source_file.source_id is source_id and source_file.partition == partition:
                return source_file
        return None

    def to_json_text(self) -> str:
        """Serialize the lockfile deterministically (two-space indent, newline)."""
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "checked_at": self.checked_at,
            "licenses": dict(sorted(self.licenses.items())),
            "files": [self._file_to_dict(source_file) for source_file in self.files],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_json_text(cls, text: str) -> Lockfile:
        """Parse and validate lockfile JSON, raising :class:`ConfigError` on bad input."""
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"lockfile is not valid JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ConfigError("lockfile must be a JSON object")
        unknown = set(payload) - _LOCKFILE_KEYS
        if unknown:
            raise ConfigError(f"lockfile has unknown keys: {', '.join(sorted(unknown))}")
        raw_files = payload.get("files")
        if not isinstance(raw_files, list):
            raise ConfigError("lockfile must contain a 'files' list")
        try:
            files = tuple(cls._file_from_dict(raw_file) for raw_file in raw_files)
            checked_at = payload.get("checked_at", "")
            if not isinstance(checked_at, str):
                raise ConfigError("lockfile checked_at must be a string")
            raw_licenses = payload.get("licenses", {})
            if not isinstance(raw_licenses, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in raw_licenses.items()
            ):
                raise ConfigError("lockfile licenses must be a string-to-string object")
            schema_version = payload.get("schema_version", 1)
            if not isinstance(schema_version, int):
                raise ConfigError("lockfile schema_version must be an integer")
            return cls(
                files=files,
                checked_at=checked_at,
                licenses=raw_licenses,
                schema_version=schema_version,
            )
        except ValueError as exc:
            raise ConfigError(f"invalid lockfile entry: {exc}") from exc

    @staticmethod
    def _file_to_dict(source_file: SourceFile) -> dict[str, Any]:
        return {
            "source_id": source_file.source_id.value,
            "partition": source_file.partition,
            "url": source_file.url,
            "filename": source_file.filename,
            "size_bytes": source_file.size_bytes,
            "sha256": source_file.sha256,
            "mutable": source_file.mutable,
            "encoding_hint": source_file.encoding_hint,
        }

    @staticmethod
    def _file_from_dict(raw: object) -> SourceFile:
        if not isinstance(raw, dict):
            raise ConfigError("each lockfile 'files' entry must be an object")
        unknown = set(raw) - _SOURCE_FILE_KEYS
        if unknown:
            raise ConfigError(f"lockfile file entry has unknown keys: {', '.join(sorted(unknown))}")
        missing = _REQUIRED_SOURCE_FILE_KEYS - set(raw)
        if missing:
            raise ConfigError(f"lockfile file entry is missing keys: {', '.join(sorted(missing))}")
        try:
            source_id = SourceId(raw["source_id"])
        except ValueError as exc:
            raise ConfigError(f"unknown source_id in lockfile: {raw['source_id']!r}") from exc
        partition = raw["partition"]
        url = raw["url"]
        filename = raw["filename"]
        size_bytes = raw["size_bytes"]
        sha256 = raw["sha256"]
        mutable = raw.get("mutable", False)
        encoding_hint = raw.get("encoding_hint")
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool):
            raise ConfigError("lockfile size_bytes must be an integer")
        for name, value in (
            ("partition", partition),
            ("url", url),
            ("filename", filename),
            ("sha256", sha256),
        ):
            if not isinstance(value, str):
                raise ConfigError(f"lockfile {name} must be a string")
        if not isinstance(mutable, bool):
            raise ConfigError("lockfile mutable must be a boolean")
        if encoding_hint is not None and not isinstance(encoding_hint, str):
            raise ConfigError("lockfile encoding_hint must be a string or null")
        return SourceFile(
            source_id=source_id,
            partition=partition,
            url=url,
            filename=filename,
            size_bytes=size_bytes,
            sha256=sha256,
            mutable=mutable,
            encoding_hint=encoding_hint,
        )
