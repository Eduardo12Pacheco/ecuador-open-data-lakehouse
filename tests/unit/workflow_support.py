"""Shared helpers for the GitHub Actions workflow contract tests (T14)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
RELEASE = WORKFLOWS / "release.yml"
MATRIX_OS = ["ubuntu-latest", "windows-latest", "macos-latest"]


def load_workflow(path: Path) -> dict[str, Any]:
    """Load one workflow; PyYAML parses the ``on`` key as boolean ``True``."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """Return the ``on`` mapping regardless of the YAML 1.1 boolean alias."""
    value = workflow.get("on", workflow.get(True))
    assert isinstance(value, dict)
    return value


def run_steps(job: dict[str, Any]) -> list[str]:
    return [step["run"] for step in job.get("steps", []) if "run" in step]


def uses_steps(job: dict[str, Any]) -> list[str]:
    return [step["uses"] for step in job.get("steps", []) if "uses" in step]


def all_uses() -> set[str]:
    return {
        step["uses"]
        for path in (CI, RELEASE)
        for job in load_workflow(path)["jobs"].values()
        for step in job.get("steps", [])
        if "uses" in step
    }
