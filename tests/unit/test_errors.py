"""Tests for the typed error hierarchy and its CLI exit codes."""

from __future__ import annotations

import pytest

from ecuador_lakehouse.domain.errors import (
    ArtifactVerificationError,
    ChecksumMismatchError,
    ConfigError,
    LakehouseError,
    QualityGateError,
    SourceSchemaError,
    SourceUnavailableError,
    TransformError,
)


def test_base_error_is_an_exception_with_generic_exit_code() -> None:
    error = LakehouseError("something went wrong")

    assert isinstance(error, Exception)
    assert str(error) == "something went wrong"
    assert error.exit_code == 1


@pytest.mark.parametrize(
    ("error_type", "exit_code"),
    [
        (ConfigError, 2),
        (ChecksumMismatchError, 3),
        (SourceSchemaError, 4),
        (SourceUnavailableError, 5),
        (TransformError, 6),
        (QualityGateError, 7),
        (ArtifactVerificationError, 8),
    ],
)
def test_each_error_has_its_documented_exit_code(
    error_type: type[LakehouseError], exit_code: int
) -> None:
    error = error_type("detail")

    assert isinstance(error, LakehouseError)
    assert error.exit_code == exit_code
    assert str(error) == "detail"


def test_errors_are_distinct_classes() -> None:
    names = {
        ConfigError,
        ChecksumMismatchError,
        SourceSchemaError,
        SourceUnavailableError,
        TransformError,
        QualityGateError,
        ArtifactVerificationError,
    }

    assert len(names) == 7
