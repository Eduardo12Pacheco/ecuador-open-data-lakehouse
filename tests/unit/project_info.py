"""Ground truth about the project read from ``pyproject.toml`` (not hand-copied)."""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def project_version() -> str:
    """Return the package version declared in ``pyproject.toml``."""
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    version = document["project"]["version"]
    assert isinstance(version, str)
    return version
