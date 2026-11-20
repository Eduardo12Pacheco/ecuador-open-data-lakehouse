"""Local-first analytics-engineering lakehouse over verified Ecuadorian open data."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ecuador-open-data-lakehouse")
except PackageNotFoundError:  # pragma: no cover - only for an uninstalled source tree
    __version__ = "0.1.0"

__all__ = ["__version__"]
