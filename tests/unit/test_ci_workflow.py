"""Contract tests for the CI workflow (T14, S19).

The YAML is parsed directly so a broken matrix, a missing least-privilege
permission block or a production command dropping out of CI fails here instead
of only on GitHub.
"""

from __future__ import annotations

from tests.unit.workflow_support import (
    CI,
    MATRIX_OS,
    RELEASE,
    load_workflow,
    run_steps,
    triggers,
    uses_steps,
)


def test_ci_triggers_on_main_pull_requests_and_workflow_call() -> None:
    workflow = load_workflow(CI)

    assert triggers(workflow)["push"]["branches"] == ["main"]
    assert "pull_request" in triggers(workflow)
    assert "workflow_call" in triggers(workflow)


def test_ci_has_every_required_job() -> None:
    workflow = load_workflow(CI)

    assert set(workflow["jobs"]) == {"lint", "test", "e2e", "smoke-install", "security"}


def test_ci_reruns_the_quality_gates() -> None:
    job = load_workflow(CI)["jobs"]["lint"]
    commands = "\n".join(run_steps(job))

    assert "uv sync --locked" in commands
    assert "uv lock --check" in commands
    assert "ruff check" in commands
    assert "ruff format --check" in commands
    assert "mypy" in commands
    assert "lint-imports" in commands


def test_ci_test_matrix_covers_three_operating_systems_with_utf8() -> None:
    job = load_workflow(CI)["jobs"]["test"]

    assert job["strategy"]["matrix"]["os"] == MATRIX_OS
    assert job["env"]["PYTHONUTF8"] == "1"
    commands = "\n".join(run_steps(job))
    assert "--cov-fail-under=85" in commands
    assert "uv run pytest" in commands


def test_ci_e2e_job_installs_chromium_and_runs_browser_tests() -> None:
    job = load_workflow(CI)["jobs"]["e2e"]
    commands = "\n".join(run_steps(job))

    assert "playwright install --with-deps chromium" in commands
    assert "pytest -m e2e" in commands
    assert any("upload-artifact" in step for step in uses_steps(job))


def test_ci_smoke_install_matrix_builds_the_wheel_and_runs_the_script() -> None:
    job = load_workflow(CI)["jobs"]["smoke-install"]

    assert job["strategy"]["matrix"]["os"] == MATRIX_OS
    assert job["env"]["PYTHONUTF8"] == "1"
    commands = "\n".join(run_steps(job))
    assert "uv sync --locked" in commands
    assert "uv build" in commands
    assert "scripts/smoke.py" in commands
    assert "dist/*.whl" in commands


def test_ci_security_job_runs_pip_audit_and_gitleaks_over_history() -> None:
    job = load_workflow(CI)["jobs"]["security"]
    commands = "\n".join(run_steps(job))
    uses = uses_steps(job)
    checkout = next(step for step in job["steps"] if "checkout" in step.get("uses", ""))

    assert "uv export --no-hashes --no-emit-project" in commands
    assert "pip-audit --disable-pip --no-deps" in commands
    assert any("gitleaks-action" in step for step in uses)
    assert checkout["with"]["fetch-depth"] == 0


def test_every_workflow_declares_least_privilege_permissions() -> None:
    for path in (CI, RELEASE):
        workflow = load_workflow(path)
        assert workflow["permissions"] == {"contents": "read"}
        for job in workflow["jobs"].values():
            permissions = job.get("permissions", {})
            assert permissions.get("contents", "read") in {"read", "write"}
            assert "*" not in str(permissions)
