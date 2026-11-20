"""Unit tests for parsing dbt ``run_results.json`` into domain outcomes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.transform.results import load_json, parse_run_results
from ecuador_lakehouse.domain.errors import TransformError
from ecuador_lakehouse.domain.quality import TestStatus as DbtTestStatus


def test_parses_statuses_and_uses_manifest_names() -> None:
    run_results = {
        "results": [
            {"unique_id": "test.pkg.not_null_x", "status": "pass"},
            {"unique_id": "test.pkg.unique_x", "status": "fail", "failures": 3},
            {"unique_id": "test.pkg.warn_x", "status": "warn"},
            {"unique_id": "test.pkg.skip_x", "status": "skipped"},
        ]
    }
    manifest = {
        "nodes": {
            "test.pkg.not_null_x": {"name": "not_null_x"},
            "test.pkg.unique_x": {"name": "unique_x"},
            "test.pkg.warn_x": {"name": "warn_x"},
            "test.pkg.skip_x": {"name": "skip_x"},
        }
    }

    summary = parse_run_results(run_results, manifest)

    assert [outcome.status for outcome in summary.outcomes] == [
        DbtTestStatus.PASS,
        DbtTestStatus.FAIL,
        DbtTestStatus.PASS,
        DbtTestStatus.SKIP,
    ]
    assert summary.outcomes[1].name == "unique_x"
    assert summary.outcomes[1].message == "3 failing rows"
    assert summary.failed == 1
    assert summary.ok is False


def test_unknown_status_is_a_transform_error() -> None:
    with pytest.raises(TransformError, match="unsupported"):
        parse_run_results({"results": [{"unique_id": "test.pkg.x", "status": "exploded"}]})


def test_missing_results_list_is_a_transform_error() -> None:
    with pytest.raises(TransformError, match="results"):
        parse_run_results({})


def test_load_json_reads_objects_and_rejects_missing_files(tmp_path: Path) -> None:
    path = tmp_path / "run_results.json"
    path.write_text(json.dumps({"results": []}), encoding="utf-8")

    assert load_json(path) == {"results": []}
    with pytest.raises(TransformError, match="did not write"):
        load_json(tmp_path / "missing.json")
