"""Cross-platform developer task runner.

Usage:
    uv run python scripts/dev.py check
    uv run python scripts/dev.py lint
    uv run python scripts/dev.py arch
    uv run python scripts/dev.py types
    uv run python scripts/dev.py test
    uv run python scripts/dev.py fix
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence

Command = list[str]

COMMANDS: dict[str, list[Command]] = {
    "lint": [["ruff", "check", "."]],
    "format": [["ruff", "format", "--check", "."]],
    "arch": [["lint-imports"]],
    "types": [["mypy"]],
    "test": [["pytest"]],
    "fix": [["ruff", "check", "--fix", "."], ["ruff", "format", "."]],
}
COMMANDS["check"] = [
    *COMMANDS["lint"],
    *COMMANDS["format"],
    *COMMANDS["arch"],
    *COMMANDS["types"],
    *COMMANDS["test"],
]


def _run(commands: Sequence[Command]) -> int:
    for command in commands:
        sys.stdout.write(f"$ {' '.join(command)}\n")
        sys.stdout.flush()
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the project quality gates.")
    parser.add_argument("task", choices=sorted(COMMANDS))
    args = parser.parse_args(argv)
    return _run(COMMANDS[args.task])


if __name__ == "__main__":
    raise SystemExit(main())
