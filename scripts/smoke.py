"""Cross-platform installer smoke test for a built wheel (T14, S1, S19).

The script installs the wheel into a temporary ``uv tool`` environment and then
runs the documented quickstart commands against a temporary ``LAKEHOUSE_HOME``:

    lakehouse --version
    lakehouse doctor
    lakehouse build --publish --out <tmp>
    lakehouse test
    lakehouse verify <tmp>/ecuador-lakehouse-<version>

Installing the tool resolves its dependencies from the package index, exactly
like a user running ``uv tool install``. Every command after the installation
runs with outbound HTTP(S) routed to a closed loopback port, so the quickstart
proves it works offline and a stray network access fails fast instead of hanging.
Only the standard library is imported, which keeps the script runnable from a
bare Python installation.

Usage:
    uv run python scripts/smoke.py dist/ecuador_open_data_lakehouse-0.1.0-py3-none-any.whl
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

OFFLINE_PROXY = "http://127.0.0.1:9"
DEFAULT_TIMEOUT_S = 900
_PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class SmokeError(RuntimeError):
    """A smoke-test stage failed or produced unexpected output."""


@dataclass(frozen=True, slots=True)
class Stage:
    """One completed smoke-test stage."""

    name: str
    detail: str


def base_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return the cross-platform UTF-8 environment used by every subprocess."""
    environment = dict(os.environ if base is None else base)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def offline_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment that forces every HTTP client to a closed port."""
    environment = base_env(base)
    for variable in _PROXY_VARIABLES:
        environment[variable] = OFFLINE_PROXY
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    environment["no_proxy"] = "127.0.0.1,localhost"
    return environment


def tool_executable(bin_dir: Path, platform: str | None = None) -> Path:
    """Return the installed console-script path for the current platform."""
    name = "lakehouse.exe" if (platform or sys.platform).startswith("win") else "lakehouse"
    return bin_dir / name


def _tail(text: str, limit: int = 4000) -> str:
    stripped = text.strip()
    return stripped if len(stripped) <= limit else "...\n" + stripped[-limit:]


def _run(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    stage: str,
    timeout: int,
) -> str:
    """Run one subprocess, raising ``SmokeError`` with its output on failure."""
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(env),
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as error:
        raise SmokeError(f"{stage}: executable not found: {command[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise SmokeError(f"{stage}: timed out after {timeout}s") from error
    output = (completed.stdout or "") + (completed.stderr or "")
    if completed.returncode != 0:
        raise SmokeError(
            f"{stage}: exited {completed.returncode}\n$ {' '.join(command)}\n{_tail(output)}"
        )
    return output


def _expect(stage: str, output: str, *needles: str) -> None:
    missing = [needle for needle in needles if needle not in output]
    if missing:
        raise SmokeError(f"{stage}: missing expected text {missing!r}\n{_tail(output)}")


def _artifact_dir(out: Path, version: str) -> Path:
    expected = out / f"ecuador-lakehouse-{version}"
    if expected.is_dir():
        return expected
    candidates = sorted(path for path in out.glob("ecuador-lakehouse-*") if path.is_dir())
    if not candidates:
        raise SmokeError(f"publish: no artifact directory under {out}")
    return candidates[0]


def run_smoke(wheel: Path, *, timeout: int = DEFAULT_TIMEOUT_S) -> list[Stage]:
    """Run every stage against ``wheel`` and return the completed stages."""
    wheel = wheel.resolve()
    if not wheel.is_file():
        raise SmokeError(f"wheel not found: {wheel}")
    if wheel.suffix != ".whl":
        raise SmokeError(f"not a wheel: {wheel.name}")
    if shutil.which("uv") is None:
        raise SmokeError("uv is not on PATH")

    stages: list[Stage] = []
    with tempfile.TemporaryDirectory(prefix="lakehouse-smoke-") as raw_root:
        root = Path(raw_root)
        home = root / "home"
        out = root / "artifacts"
        bin_dir = root / "bin"
        tool_dir = root / "tools"
        install_environment = base_env()
        install_environment["UV_TOOL_DIR"] = str(tool_dir)
        install_environment["UV_TOOL_BIN_DIR"] = str(bin_dir)
        _run(
            ["uv", "tool", "install", "--force", str(wheel)],
            env=install_environment,
            stage="install",
            timeout=timeout,
        )
        executable = tool_executable(bin_dir)
        if not executable.is_file():
            raise SmokeError(f"install: console script missing at {executable}")
        stages.append(Stage("install", f"uv tool environment at {bin_dir.name}"))

        environment = offline_env(install_environment)
        environment["LAKEHOUSE_HOME"] = str(home)

        output = _run([str(executable), "--version"], env=environment, stage="version", timeout=60)
        version = output.strip()
        if not _VERSION_PATTERN.match(version):
            raise SmokeError(f"version: unexpected output {version!r}")
        stages.append(Stage("version", version))

        output = _run([str(executable), "doctor"], env=environment, stage="doctor", timeout=120)
        _expect("doctor", output, "sample: OK (12 files)", "home: OK (writable)")
        stages.append(Stage("doctor", "versions, home and sample verified"))

        output = _run(
            [
                str(executable),
                "build",
                "--publish",
                "--out",
                str(out),
            ],
            env=environment,
            stage="build",
            timeout=timeout,
        )
        _expect("build", output, "publish", "ok")
        if "FAILED" in output:
            raise SmokeError(f"build: a pipeline step failed\n{_tail(output)}")
        artifact = _artifact_dir(out, version)
        stages.append(Stage("build", f"sample lakehouse built and published at {artifact.name}"))

        output = _run(
            [str(executable), "test"],
            env=environment,
            stage="test",
            timeout=timeout,
        )
        _expect("test", output, "PASS ", "data and unit tests")
        stages.append(Stage("test", output.strip().splitlines()[-1]))

        output = _run(
            [str(executable), "verify", str(artifact)],
            env=environment,
            stage="verify",
            timeout=300,
        )
        _expect("verify", output, "verified 14 tables")
        stages.append(Stage("verify", "artifact checksums, schemas and row counts match"))
    return stages


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point: run the smoke test against one wheel path."""
    parser = argparse.ArgumentParser(
        description="Install a built wheel and exercise its offline quickstart."
    )
    parser.add_argument("wheel", type=Path, help="Path to the built .whl file.")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_S,
        help=f"Per-command timeout in seconds (default: {DEFAULT_TIMEOUT_S}).",
    )
    args = parser.parse_args(argv)
    try:
        stages = run_smoke(args.wheel, timeout=args.timeout)
    except SmokeError as error:
        sys.stderr.write(f"smoke: FAILED\n{error}\n")
        return 1
    for stage in stages:
        sys.stdout.write(f"{stage.name}: ok ({stage.detail})\n")
    sys.stdout.write(f"smoke: ok ({len(stages)} stages)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
