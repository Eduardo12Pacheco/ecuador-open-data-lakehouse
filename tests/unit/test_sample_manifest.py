"""Tests for the bundled-sample manifest value objects and codec (S3)."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sample import (
    ControlTotal,
    SampleFile,
    SampleManifest,
)
from ecuador_lakehouse.domain.sources import SourceId

SHA = "b" * 64
DERIVED = "c" * 64


def make_sample_file(**overrides: object) -> SampleFile:
    values: dict[str, object] = {
        "name": "sri_tax_collection_2019.csv.gz",
        "source_id": SourceId.SRI_TAX,
        "partition": "2019",
        "size_bytes": 223_420,
        "sha256": SHA,
        "rows": 24_035,
        "derived_from_sha256": DERIVED,
    }
    values.update(overrides)
    return SampleFile(**values)  # type: ignore[arg-type]


def make_manifest() -> SampleManifest:
    return SampleManifest(
        builder_version="0.1.0",
        checked_at="2026-11-19",
        files=(
            make_sample_file(),
            make_sample_file(
                name="bce_cnt_quarterly.csv.gz",
                source_id=SourceId.BCE_CNT,
                partition="2000Q1-2021Q1",
                size_bytes=433_941,
                rows=32_470,
            ),
        ),
    )


def test_sample_manifest_round_trips_through_json() -> None:
    manifest = make_manifest()

    restored = SampleManifest.from_json_text(manifest.to_json_text())

    assert restored == manifest


def test_manifest_total_bytes_and_lookup() -> None:
    manifest = make_manifest()

    assert manifest.total_bytes == 223_420 + 433_941
    assert manifest.find("bce_cnt_quarterly.csv.gz") is manifest.files[0]
    assert manifest.find("missing.csv") is None
    assert manifest.by_source(SourceId.SRI_TAX) == (manifest.files[1],)


def test_manifest_json_is_deterministic_and_has_the_documented_keys() -> None:
    manifest = make_manifest()

    text = manifest.to_json_text()
    payload = json.loads(text)

    assert text == manifest.to_json_text()
    assert payload["schema_version"] == 1
    assert payload["builder_version"] == "0.1.0"
    assert payload["checked_at"] == "2026-11-19"
    assert payload["files"][0] == {
        "name": "bce_cnt_quarterly.csv.gz",
        "source_id": "bce_cnt",
        "partition": "2000Q1-2021Q1",
        "bytes": 433_941,
        "sha256": SHA,
        "rows": 32_470,
        "derived_from_sha256": DERIVED,
    }
    assert payload["files"][1]["name"] == "sri_tax_collection_2019.csv.gz"


def test_manifest_files_are_sorted_by_name_in_json() -> None:
    manifest = SampleManifest(
        builder_version="0.1.0",
        checked_at="2026-11-19",
        files=(make_sample_file(), make_sample_file(name="aaa.csv.gz")),
    )

    names = [entry["name"] for entry in json.loads(manifest.to_json_text())["files"]]

    assert names == ["aaa.csv.gz", "sri_tax_collection_2019.csv.gz"]


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"sha256": "nope"}, "sha256"),
        ({"sha256": "A" * 64}, "sha256"),
        ({"derived_from_sha256": "nope"}, "derived"),
        ({"size_bytes": -1}, "size"),
        ({"rows": -1}, "rows"),
        ({"name": ""}, "name"),
        ({"name": "../evil.csv.gz"}, "name"),
        ({"name": "sub/file.csv.gz"}, "name"),
        ({"partition": " "}, "partition"),
    ],
)
def test_sample_file_rejects_invalid_values(overrides: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        make_sample_file(**overrides)


def test_manifest_rejects_duplicate_names_and_bad_metadata() -> None:
    with pytest.raises(ConfigError, match="duplicate"):
        SampleManifest(
            builder_version="0.1.0",
            checked_at="2026-11-19",
            files=(make_sample_file(), make_sample_file()),
        )
    with pytest.raises(ConfigError, match="checked_at"):
        SampleManifest(builder_version="0.1.0", checked_at="yesterday", files=(make_sample_file(),))
    with pytest.raises(ConfigError, match="builder_version"):
        SampleManifest(builder_version=" ", checked_at="2026-11-19", files=(make_sample_file(),))
    with pytest.raises(ConfigError, match="at least one file"):
        SampleManifest(builder_version="0.1.0", checked_at="2026-11-19", files=())


def test_manifest_rejects_unknown_or_missing_json_keys() -> None:
    payload = json.loads(make_manifest().to_json_text())
    payload["surprise"] = True
    with pytest.raises(ConfigError, match="unknown"):
        SampleManifest.from_json_text(json.dumps(payload))

    payload = json.loads(make_manifest().to_json_text())
    del payload["files"][0]["rows"]
    with pytest.raises(ConfigError, match="missing"):
        SampleManifest.from_json_text(json.dumps(payload))


def test_control_total_rejects_invalid_values() -> None:
    total = ControlTotal(
        source_id=SourceId.SRI_TAX,
        period_year=2025,
        expected_total_usd=Decimal("21500870934.42"),
        is_frozen=True,
        as_of_date="2026-11-19",
    )
    assert total.expected_total_usd == Decimal("21500870934.42")

    with pytest.raises(ValueError, match="period_year"):
        ControlTotal(SourceId.SRI_TAX, 0, Decimal("1"), True, "2026-11-19")
    with pytest.raises(ValueError, match="expected_total_usd"):
        ControlTotal(SourceId.SRI_TAX, 2025, Decimal("NaN"), True, "2026-11-19")
    with pytest.raises(ValueError, match="as_of_date"):
        ControlTotal(SourceId.SRI_TAX, 2025, Decimal("1"), True, "")
