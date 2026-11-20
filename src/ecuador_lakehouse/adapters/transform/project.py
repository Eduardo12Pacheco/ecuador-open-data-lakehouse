"""Materialize the packaged dbt project under ``$LAKEHOUSE_HOME`` (D18).

The wheel ships the project as package data, but dbt writes ``target/``,
``logs/`` and ``dbt_packages/`` next to the project it runs. Copying the
project into the user data directory before every invocation keeps the repo and
the installed package clean and makes runs reproducible.
"""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

PROJECT_RESOURCE = ("dbt_project",)
IGNORED_PROJECT_ENTRIES = ("target", "logs", "dbt_packages", "__pycache__")


def copy_project(destination: Path) -> Path:
    """Copy the packaged dbt project into ``destination`` and return it."""
    source = resources.files("ecuador_lakehouse").joinpath(*PROJECT_RESOURCE)
    with resources.as_file(source) as source_path:
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            source_path,
            destination,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("*.pyc", *IGNORED_PROJECT_ENTRIES),
        )
    return destination


def write_profiles(destination: Path, *, warehouse_path: Path, threads: int) -> Path:
    """Write a DuckDB ``profiles.yml`` with absolute paths and return its path."""
    destination.mkdir(parents=True, exist_ok=True)
    profiles_path = destination / "profiles.yml"
    database_path = warehouse_path.resolve().as_posix()
    profiles_path.write_text(
        "ecuador_lakehouse:\n"
        "  target: dev\n"
        "  outputs:\n"
        "    dev:\n"
        "      type: duckdb\n"
        f'      path: "{database_path}"\n'
        f"      threads: {threads}\n",
        encoding="utf-8",
    )
    return profiles_path
