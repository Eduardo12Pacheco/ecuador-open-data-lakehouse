"""Inventory tests for the committed ``sources.lock.json`` (S4)."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from ecuador_lakehouse.adapters.sources.http_fetcher import DEFAULT_ALLOWED_HOSTS
from ecuador_lakehouse.domain.sources import Lockfile, SourceId

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def load_lockfile() -> Lockfile:
    text = (
        resources.files("ecuador_lakehouse")
        .joinpath("sources.lock.json")
        .read_text(encoding="utf-8")
    )
    return Lockfile.from_json_text(text)


def test_the_lockfile_pins_the_twelve_documented_files() -> None:
    lockfile = load_lockfile()

    assert isinstance(lockfile, Lockfile)
    assert lockfile.schema_version == 1
    assert lockfile.checked_at == "2026-11-19"
    assert len(lockfile.files) == 12
    assert [file.source_id for file in lockfile.files].count(SourceId.SRI_TAX) == 10
    assert [file.source_id for file in lockfile.files].count(SourceId.BCE_CNT) == 1
    assert [file.source_id for file in lockfile.files].count(SourceId.INEC_CPI) == 1


def test_the_lockfile_records_license_metadata_per_source() -> None:
    lockfile = load_lockfile()

    assert lockfile.licenses == {
        "sri_tax": "cc-by",
        "bce_cnt": "cc-by",
        "inec_cpi": "cc-by-4.0",
    }
    assert lockfile.find(SourceId.SRI_TAX, "2026") is not None


def test_only_the_current_sri_file_is_mutable() -> None:
    lockfile = load_lockfile()

    mutable = [file for file in lockfile.files if file.mutable]

    assert [file.partition for file in mutable] == ["2026"]


def test_pinned_checksums_match_the_plan_for_known_files() -> None:
    lockfile = load_lockfile()

    bce = lockfile.find(SourceId.BCE_CNT, "2000Q1-2021Q1")
    inec = lockfile.find(SourceId.INEC_CPI, "2024-12")
    sri_2017 = lockfile.find(SourceId.SRI_TAX, "2017")
    sri_2026 = lockfile.find(SourceId.SRI_TAX, "2026")

    assert bce is not None
    assert bce.size_bytes == 6_108_986
    assert bce.sha256 == "b90e0e5a403a44ecd862969b72c6fc900f730e62d7b4cffecaa55116ed81e187"
    assert inec is not None
    assert inec.size_bytes == 7_479_409
    assert inec.sha256 == "e7b854b4f422d23f622e3c474ebc47a0bc46caa9d15f0a3670bce7f67fc697f4"
    assert sri_2017 is not None
    assert sri_2017.size_bytes == 84_892_997
    assert sri_2017.sha256 == "dd14c281d082417342daa2e3060ba1df759f2c29a2f7144e4ce91e62a79753d4"
    assert sri_2026 is not None
    assert sri_2026.size_bytes == 83_320_465
    assert sri_2026.sha256 == "90878717f7faadaf5f3e815ca35c6164b059ae97b7ef8b8722e7b843918b420f"


def test_every_locked_url_uses_an_allow_listed_https_host() -> None:
    lockfile = load_lockfile()

    for source_file in lockfile.files:
        url = source_file.url
        assert url.startswith("https://")
        host = url.split("/")[2]
        assert host in DEFAULT_ALLOWED_HOSTS, source_file.filename


def test_the_lockfile_round_trips_without_losing_metadata() -> None:
    lockfile = load_lockfile()

    assert Lockfile.from_json_text(lockfile.to_json_text()) == lockfile


def test_recorded_head_metadata_agrees_with_the_pins() -> None:
    recorded = json.loads((FIXTURES / "http" / "head_metadata.json").read_text(encoding="utf-8"))
    lockfile = load_lockfile()
    by_url = {source_file.url: source_file for source_file in lockfile.files}

    assert len(recorded["files"]) == 4
    for entry in recorded["files"]:
        source_file = by_url[entry["url"]]
        assert entry["status"] == 200
        assert entry["accept_ranges"] == "bytes"
        assert entry["content_length"] == source_file.size_bytes, source_file.filename


def test_the_packaged_lockfile_is_valid_json() -> None:
    path = Path(__file__).resolve().parents[3] / "src" / "ecuador_lakehouse" / "sources.lock.json"

    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert len(payload["files"]) == 12
