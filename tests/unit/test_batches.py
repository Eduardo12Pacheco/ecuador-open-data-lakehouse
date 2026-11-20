"""Tests for deterministic batch identifiers and ledger records."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from ecuador_lakehouse.domain.batches import BatchRecord, BatchStatus, make_batch_id
from ecuador_lakehouse.domain.sources import SourceId

SHA = "b" * 64


def test_make_batch_id_is_the_documented_sha256_prefix() -> None:
    material = f"sri_tax|2024|{SHA}"
    expected = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    assert make_batch_id(SourceId.SRI_TAX, "2024", SHA) == expected
    assert len(expected) == 16


def test_make_batch_id_is_deterministic_and_input_sensitive() -> None:
    base = make_batch_id(SourceId.SRI_TAX, "2024", SHA)

    assert make_batch_id(SourceId.SRI_TAX, "2024", SHA) == base
    assert make_batch_id(SourceId.SRI_TAX, "2025", SHA) != base
    assert make_batch_id(SourceId.BCE_CNT, "2024", SHA) != base
    assert make_batch_id(SourceId.SRI_TAX, "2024", "c" * 64) != base


@pytest.mark.parametrize(("raw", "match"), [("", "partition"), (" ", "partition")])
def test_make_batch_id_requires_a_partition(raw: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        make_batch_id(SourceId.SRI_TAX, raw, SHA)


@pytest.mark.parametrize("sha", ["", "abc", "z" * 64])
def test_make_batch_id_requires_a_sha256(sha: str) -> None:
    with pytest.raises(ValueError, match="sha256"):
        make_batch_id(SourceId.SRI_TAX, "2024", sha)


def test_batch_status_values_are_stable() -> None:
    assert [status.value for status in BatchStatus] == ["loaded", "skipped", "replaced"]


def test_batch_record_exposes_its_ledger_fields() -> None:
    loaded_at = datetime(2026, 11, 19, tzinfo=UTC)
    record = BatchRecord(
        batch_id="0123456789abcdef",
        source_id=SourceId.SRI_TAX,
        partition="2024",
        source_sha256=SHA,
        row_count=24_423,
        status=BatchStatus.LOADED,
        mode="sample",
        loaded_at=loaded_at,
        is_current=True,
    )

    assert record.batch_id == "0123456789abcdef"
    assert record.status is BatchStatus.LOADED
    assert record.is_current is True


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"batch_id": "xyz"}, "batch_id"),
        ({"source_sha256": "abc"}, "sha256"),
        ({"row_count": -1}, "row_count"),
        ({"mode": ""}, "mode"),
    ],
)
def test_batch_record_rejects_invalid_values(overrides: dict[str, object], match: str) -> None:
    values: dict[str, object] = {
        "batch_id": "0123456789abcdef",
        "source_id": SourceId.SRI_TAX,
        "partition": "2024",
        "source_sha256": SHA,
        "row_count": 1,
        "status": BatchStatus.LOADED,
        "mode": "sample",
        "loaded_at": datetime(2026, 11, 19, tzinfo=UTC),
        "is_current": True,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=match):
        BatchRecord(**values)  # type: ignore[arg-type]
