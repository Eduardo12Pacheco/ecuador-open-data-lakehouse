"""Unit tests for the installer smoke script (T14)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from scripts import smoke

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_base_env_sets_utf8_without_forcing_proxies() -> None:
    environment = smoke.base_env({"PATH": "/usr/bin"})

    assert environment["PYTHONUTF8"] == "1"
    assert environment["PYTHONIOENCODING"] == "utf-8"
    assert "HTTP_PROXY" not in environment


def test_offline_env_routes_every_proxy_variable_to_a_closed_port() -> None:
    environment = smoke.offline_env({"PATH": "/usr/bin", "HTTP_PROXY": "http://proxy"})

    assert environment["PATH"] == "/usr/bin"
    for name in smoke._PROXY_VARIABLES:
        assert environment[name] == smoke.OFFLINE_PROXY
    assert environment["NO_PROXY"] == "127.0.0.1,localhost"
    assert environment["PYTHONUTF8"] == "1"
    assert environment["PYTHONIOENCODING"] == "utf-8"


def test_tool_executable_uses_the_platform_extension() -> None:
    bin_dir = Path("tools") / "bin"

    assert smoke.tool_executable(bin_dir, "win32") == bin_dir / "lakehouse.exe"
    assert smoke.tool_executable(bin_dir, "linux") == bin_dir / "lakehouse"
    assert smoke.tool_executable(bin_dir, "darwin") == bin_dir / "lakehouse"


def test_run_smoke_rejects_a_missing_wheel(tmp_path: Path) -> None:
    with pytest.raises(smoke.SmokeError, match="wheel not found"):
        smoke.run_smoke(tmp_path / "missing-0.1.0-py3-none-any.whl")


def test_run_smoke_rejects_a_non_wheel_file(tmp_path: Path) -> None:
    archive = tmp_path / "package.tar.gz"
    archive.write_bytes(b"not a wheel")

    with pytest.raises(smoke.SmokeError, match="not a wheel"):
        smoke.run_smoke(archive)


def test_expect_lists_the_missing_text() -> None:
    with pytest.raises(smoke.SmokeError, match="sample: OK"):
        smoke._expect("doctor", "home: OK", "sample: OK", "home: OK")


def test_artifact_dir_falls_back_to_the_only_published_directory(tmp_path: Path) -> None:
    published = tmp_path / "artifacts" / "ecuador-lakehouse-1.2.3"
    published.mkdir(parents=True)

    assert smoke._artifact_dir(tmp_path / "artifacts", "1.2.3") == published
    assert smoke._artifact_dir(tmp_path / "artifacts", "9.9.9") == published


def test_artifact_dir_fails_when_nothing_was_published(tmp_path: Path) -> None:
    with pytest.raises(smoke.SmokeError, match="no artifact directory"):
        smoke._artifact_dir(tmp_path / "artifacts", "1.2.3")


def test_script_runs_with_the_repository_python() -> None:
    assert Path(smoke.__file__).resolve().parent == REPO_ROOT / "scripts"
    assert sys.version_info >= (3, 12)
