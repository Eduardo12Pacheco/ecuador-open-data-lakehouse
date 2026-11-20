"""Typed domain errors mapped to documented process exit codes.

Every error raised deliberately by the lakehouse inherits from
:class:`LakehouseError` and declares the exit code the CLI must return.
Unexpected exceptions always surface as exit code 1 through the CLI.
"""

from __future__ import annotations

from typing import ClassVar


class LakehouseError(Exception):
    """Base class for every expected lakehouse failure."""

    exit_code: ClassVar[int] = 1


class ConfigError(LakehouseError):
    """Invalid configuration, settings or command-line usage."""

    exit_code: ClassVar[int] = 2


class ChecksumMismatchError(LakehouseError):
    """A downloaded file does not match its pinned SHA-256 checksum."""

    exit_code: ClassVar[int] = 3


class SourceSchemaError(LakehouseError):
    """An upstream file does not match the schema the parser requires."""

    exit_code: ClassVar[int] = 4


class UnsafeArchiveError(SourceSchemaError):
    """A ZIP archive is malformed or would escape the extraction directory."""

    exit_code: ClassVar[int] = 4


class SourceUnavailableError(LakehouseError):
    """An upstream source cannot be reached or read."""

    exit_code: ClassVar[int] = 5


class TransformError(LakehouseError):
    """The dbt transformation layer failed."""

    exit_code: ClassVar[int] = 6


class QualityGateError(LakehouseError):
    """At least one data or unit test failed, so the quality gate is closed."""

    exit_code: ClassVar[int] = 7


class ArtifactVerificationError(LakehouseError):
    """A published artifact is missing, corrupt or does not match its manifest."""

    exit_code: ClassVar[int] = 8
