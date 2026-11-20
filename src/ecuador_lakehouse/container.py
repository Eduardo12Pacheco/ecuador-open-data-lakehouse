"""Composition root: wires settings and, in later tasks, adapters and use cases.

Only this module (and the CLI entry point) may know every layer; the wiring is
kept explicit instead of using a dependency-injection framework.
"""

from __future__ import annotations

from dataclasses import dataclass

from ecuador_lakehouse.config import Settings, get_settings


@dataclass(frozen=True, slots=True)
class Container:
    """Resolved dependencies for one CLI invocation."""

    settings: Settings


def build_container(settings: Settings | None = None) -> Container:
    """Build the container from explicit settings or the process environment."""
    return Container(settings=settings if settings is not None else get_settings())
