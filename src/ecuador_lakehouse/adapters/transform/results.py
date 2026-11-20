"""Parse dbt ``run_results.json`` into the domain quality summary (S11)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ecuador_lakehouse.domain.errors import TransformError
from ecuador_lakehouse.domain.quality import QualitySummary, TestOutcome, TestStatus

_STATUS_MAP: dict[str, TestStatus] = {
    "pass": TestStatus.PASS,
    "success": TestStatus.PASS,
    # ``warn`` data tests are warnings by configuration, not quality-gate failures.
    "warn": TestStatus.PASS,
    "fail": TestStatus.FAIL,
    "error": TestStatus.ERROR,
    "skipped": TestStatus.SKIP,
}


def load_json(path: Path) -> Mapping[str, Any]:
    """Read a JSON object from disk, raising :class:`TransformError` when unusable."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TransformError(f"dbt did not write {path.name} at {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise TransformError(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TransformError(f"{path} does not contain a JSON object")
    return payload


def _node_names(manifest: Mapping[str, Any] | None) -> dict[str, str]:
    if manifest is None:
        return {}
    nodes = manifest.get("nodes")
    if not isinstance(nodes, dict):
        return {}
    return {
        unique_id: str(node.get("name", unique_id))
        for unique_id, node in nodes.items()
        if isinstance(node, dict)
    }


def parse_run_results(
    run_results: Mapping[str, Any],
    manifest: Mapping[str, Any] | None = None,
) -> QualitySummary:
    """Map every dbt test result to a :class:`TestOutcome`."""
    raw_results = run_results.get("results")
    if not isinstance(raw_results, list):
        raise TransformError("run_results.json has no results list")
    names = _node_names(manifest)
    outcomes: list[TestOutcome] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            raise TransformError("run_results.json contains a non-object result")
        unique_id = str(raw.get("unique_id", ""))
        status_text = str(raw.get("status", "")).lower()
        status = _STATUS_MAP.get(status_text)
        if not unique_id or status is None:
            raise TransformError(
                f"unsupported dbt result {unique_id or '<missing>'} with status {status_text!r}"
            )
        message = str(raw.get("message") or "")
        failures = raw.get("failures")
        if failures not in (None, 0) and not message:
            message = f"{failures} failing rows"
        outcomes.append(
            TestOutcome(
                name=names.get(unique_id, unique_id.rsplit(".", 1)[-1]),
                status=status,
                message=message,
            )
        )
    return QualitySummary.from_outcomes(outcomes)
