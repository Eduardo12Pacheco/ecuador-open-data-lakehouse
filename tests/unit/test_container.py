"""Tests for the composition root stub."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecuador_lakehouse.config import Settings, get_settings
from ecuador_lakehouse.container import Container, build_container


def test_build_container_uses_explicit_settings(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "home")

    container = build_container(settings)

    assert isinstance(container, Container)
    assert container.settings is settings


def test_build_container_defaults_to_get_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LAKEHOUSE_HOME", str(tmp_path / "home"))

    container = build_container()

    assert container.settings is get_settings()
