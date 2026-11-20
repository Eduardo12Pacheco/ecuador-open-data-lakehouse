"""Architecture enforcement for the hexagonal layering (S17).

Two independent mechanisms guard the dependency rule:

* import-linter checks the declared layer, forbidden-import and adapter
  independence contracts from ``pyproject.toml``;
* an AST scan proves ``domain/`` imports only the standard library and itself,
  even if a future contract entry is forgotten.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
DOMAIN_ROOT = SRC_ROOT / "ecuador_lakehouse" / "domain"
APPLICATION_ROOT = SRC_ROOT / "ecuador_lakehouse" / "application"

APPLICATION_FORBIDDEN = frozenset(
    {
        "ecuador_lakehouse.adapters",
        "ecuador_lakehouse.config",
        "ecuador_lakehouse.logging_setup",
        "dbt",
        "duckdb",
        "httpx",
        "jinja2",
        "rich",
        "typer",
    }
)


def imported_modules(path: Path) -> set[str]:
    """Return the absolute module names imported by one Python source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    parts = path.parts
    package_index = max(index for index, part in enumerate(parts) if part == "ecuador_lakehouse")
    package_parts = parts[package_index:-1]
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[: len(package_parts) - (node.level - 1)]
                prefix = ".".join(base)
                module = f"{prefix}.{node.module}" if node.module else prefix
            else:
                module = node.module or ""
            if module:
                modules.add(module)
    return modules


def domain_violations(root: Path = DOMAIN_ROOT) -> list[str]:
    """Return human-readable descriptions of forbidden imports under ``root``."""
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for module in imported_modules(path):
            top_level = module.split(".", 1)[0]
            if top_level == "ecuador_lakehouse":
                if not module.startswith("ecuador_lakehouse.domain"):
                    violations.append(f"{path.name}: imports {module}")
            elif top_level not in sys.stdlib_module_names and top_level != "__future__":
                violations.append(f"{path.name}: imports non-stdlib {module}")
    return violations


def application_violations(root: Path = APPLICATION_ROOT) -> list[str]:
    """Return imports from ``application/`` that must never happen."""
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        for module in imported_modules(path):
            for forbidden in APPLICATION_FORBIDDEN:
                if module == forbidden or module.startswith(f"{forbidden}."):
                    violations.append(f"{path.name}: imports {module}")
    return violations


def test_lint_imports_contracts_pass() -> None:
    executable = shutil.which("lint-imports")
    assert executable is not None, "lint-imports must be installed through the dev dependency group"

    completed = subprocess.run(
        [executable, "--no-logo"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, (
        f"lint-imports failed:\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def test_domain_imports_are_standard_library_or_domain_only() -> None:
    assert domain_violations() == []


def test_application_does_not_import_adapters_or_third_party_io() -> None:
    assert application_violations() == []


def test_purity_check_detects_a_third_party_domain_import(tmp_path: Path) -> None:
    package = tmp_path / "ecuador_lakehouse" / "domain"
    package.mkdir(parents=True)
    (package / "leaky.py").write_text("import duckdb\n", encoding="utf-8")

    violations = domain_violations(package)

    assert len(violations) == 1
    assert "duckdb" in violations[0]


def test_purity_check_detects_an_upward_relative_import(tmp_path: Path) -> None:
    package = tmp_path / "ecuador_lakehouse" / "domain"
    package.mkdir(parents=True)
    (package / "leaky.py").write_text("from ..config import Settings\n", encoding="utf-8")

    violations = domain_violations(package)

    assert len(violations) == 1
    assert "ecuador_lakehouse.config" in violations[0]


@pytest.mark.usefixtures("tmp_path")
def test_purity_check_accepts_domain_and_stdlib_imports(tmp_path: Path) -> None:
    package = tmp_path / "ecuador_lakehouse" / "domain"
    package.mkdir(parents=True)
    (package / "clean.py").write_text(
        "from __future__ import annotations\n\nimport json\n\nfrom .text import normalize_key\n",
        encoding="utf-8",
    )

    assert domain_violations(package) == []
