"""Tests for the source value objects and the pure lockfile codec."""

from __future__ import annotations

import json

import pytest

from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sources import LicenseInfo, Lockfile, SourceFile, SourceId

SHA = "a" * 64


def make_source_file(**overrides: object) -> SourceFile:
    values: dict[str, object] = {
        "source_id": SourceId.SRI_TAX,
        "partition": "2024",
        "url": "https://descargas.sri.gob.ec/download/datosAbiertos/sri_recaudacion_2024.csv",
        "filename": "sri_recaudacion_2024.csv",
        "size_bytes": 96_066_889,
        "sha256": SHA,
        "mutable": False,
        "encoding_hint": "utf-8-sig",
    }
    values.update(overrides)
    return SourceFile(**values)  # type: ignore[arg-type]


def test_source_ids_have_stable_string_values() -> None:
    assert [source.value for source in SourceId] == ["sri_tax", "bce_cnt", "inec_cpi"]
    assert SourceId("bce_cnt") is SourceId.BCE_CNT


def test_source_file_is_a_frozen_value_object() -> None:
    source_file = make_source_file()

    with pytest.raises(AttributeError):
        source_file.size_bytes = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"sha256": "abc"}, "sha256"),
        ({"sha256": "A" * 64}, "sha256"),
        ({"size_bytes": -1}, "size"),
        ({"partition": " "}, "partition"),
        ({"filename": ""}, "filename"),
        ({"filename": "../escape.csv"}, "filename"),
        ({"filename": "sub/dir.csv"}, "filename"),
        ({"url": ""}, "url"),
        ({"encoding_hint": ""}, "encoding"),
    ],
)
def test_source_file_rejects_invalid_values(overrides: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        make_source_file(**overrides)


def test_license_info_requires_an_identifier() -> None:
    assert LicenseInfo(license_id="cc-by", title="CC BY").license_id == "cc-by"
    with pytest.raises(ValueError, match="license"):
        LicenseInfo(license_id="")


def make_lockfile() -> Lockfile:
    return Lockfile(
        checked_at="2026-11-19",
        licenses={"sri_tax": "cc-by", "bce_cnt": "cc-by", "inec_cpi": "cc-by"},
        files=(make_source_file(), make_source_file(partition="2025", filename="sri_2025.csv")),
    )


def test_lockfile_round_trips_through_json() -> None:
    lockfile = make_lockfile()

    restored = Lockfile.from_json_text(lockfile.to_json_text())

    assert restored == lockfile
    assert restored.files[0].source_id is SourceId.SRI_TAX


def test_lockfile_json_has_the_documented_shape() -> None:
    payload = json.loads(make_lockfile().to_json_text())

    assert payload["schema_version"] == 1
    assert payload["checked_at"] == "2026-11-19"
    assert payload["licenses"] == {"sri_tax": "cc-by", "bce_cnt": "cc-by", "inec_cpi": "cc-by"}
    assert len(payload["files"]) == 2
    assert payload["files"][0]["sha256"] == SHA
    assert payload["files"][0]["mutable"] is False
    assert payload["files"][0]["encoding_hint"] == "utf-8-sig"


def test_lockfile_can_find_a_file_by_source_and_partition() -> None:
    lockfile = make_lockfile()

    assert lockfile.find(SourceId.SRI_TAX, "2025") == lockfile.files[1]
    assert lockfile.find(SourceId.SRI_TAX, "1999") is None
    assert lockfile.find(SourceId.BCE_CNT, "2025") is None


def test_lockfile_accepts_an_empty_license_map() -> None:
    lockfile = Lockfile(files=())

    assert lockfile.licenses == {}
    assert lockfile.to_json_text().endswith("\n")


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"files": "nope"}',
        '{"files": [{"source_id": "bogus"}]}',
        '{"files": [{"source_id": "sri_tax", "partition": "2024", "url": "u", '
        '"filename": "f", "size_bytes": 1, "sha256": "abc"}]}',
        '{"files": [], "checked_at": "19/11/2026"}',
        '{"files": [], "extra": true}',
        '{"files": [{"source_id": "sri_tax", "partition": "2024", "url": "u", '
        '"filename": "f", "size_bytes": 1, "sha256": "' + SHA + '", "surprise": 1}]}',
    ],
)
def test_lockfile_rejects_malformed_json(raw: str) -> None:
    with pytest.raises(ConfigError):
        Lockfile.from_json_text(raw)


def test_lockfile_rejects_duplicate_files() -> None:
    duplicate = make_source_file()

    with pytest.raises(ConfigError, match="duplicate"):
        Lockfile(files=(duplicate, duplicate))
