"""Contract tests for the release workflow (T14, S20)."""

from __future__ import annotations

import re

from tests.unit.workflow_support import (
    CI,
    RELEASE,
    all_uses,
    load_workflow,
    run_steps,
    triggers,
    uses_steps,
)

PINNED_ACTION = re.compile(r"^[\w.-]+/[\w.-]+@v\d+$")


def test_release_workflow_is_tag_driven_and_reuses_ci() -> None:
    workflow = load_workflow(RELEASE)
    jobs = workflow["jobs"]

    assert triggers(workflow) == {"push": {"tags": ["v*"]}}
    assert set(jobs) == {"ci", "build", "artifact", "release"}
    assert jobs["ci"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["build"]["needs"] == "ci"
    assert jobs["release"]["needs"] == ["build", "artifact"]
    assert jobs["release"]["permissions"] == {"contents": "write"}


def test_release_builds_and_uploads_the_wheel_and_sdist() -> None:
    steps = load_workflow(RELEASE)["jobs"]["build"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps)
    uses = [step["uses"] for step in steps if "uses" in step]

    assert "uv build" in commands
    assert any("upload-artifact" in step for step in uses)


def test_release_publishes_a_verified_sample_artifact_zip() -> None:
    job = load_workflow(RELEASE)["jobs"]["artifact"]
    commands = "\n".join(run_steps(job))
    uses = uses_steps(job)

    assert "download-artifact" in " ".join(uses)
    assert "uv tool install" in commands
    assert "lakehouse build" in commands
    assert "lakehouse publish" in commands
    assert "lakehouse verify" in commands
    assert "ecuador-lakehouse-artifact-" in commands
    assert ".zip" in commands
    assert any("upload-artifact" in step for step in uses)


def test_release_creates_a_github_release_with_checksums_and_notes() -> None:
    job = load_workflow(RELEASE)["jobs"]["release"]
    commands = "\n".join(run_steps(job))
    uses = uses_steps(job)

    assert "download-artifact" in " ".join(uses)
    assert "git-cliff --latest --strip header" in commands
    assert "sha256sum" in commands
    assert 'gh release create "$GITHUB_REF_NAME"' in commands
    assert "--notes-file RELEASE_NOTES.md" in commands


def test_actions_are_pinned_to_major_versions() -> None:
    for path in (CI, RELEASE):
        workflow = load_workflow(path)
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                action = step.get("uses", "")
                if not action or action.startswith("./"):
                    continue
                assert PINNED_ACTION.match(action), f"{path.name}: unpinned action {action}"


def test_required_action_majors_follow_the_plan() -> None:
    uses = all_uses()

    assert "actions/checkout@v7" in uses
    assert "astral-sh/setup-uv@v7" in uses
    assert "actions/upload-artifact@v7" in uses
    assert "actions/download-artifact@v8" in uses
    assert "gitleaks/gitleaks-action@v3" in uses
