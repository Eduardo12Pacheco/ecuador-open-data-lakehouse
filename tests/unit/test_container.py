"""Tests for the composition root stub."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecuador_lakehouse import __version__
from ecuador_lakehouse.adapters.sources.http_fetcher import HttpSourceFetcher
from ecuador_lakehouse.adapters.sources.sample_fetcher import SampleSourceFetcher
from ecuador_lakehouse.config import Settings, get_settings
from ecuador_lakehouse.container import (
    Container,
    build_container,
    build_sample_builder,
    load_lockfile,
)
from ecuador_lakehouse.domain.sources import SourceId


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


def test_build_sample_builder_wires_the_maintainer_command(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "home")

    builder = build_sample_builder(
        settings,
        cache_dir=tmp_path / "cache",
        output_dir=tmp_path / "sample_data",
        seed_dir=tmp_path / "seeds",
    )

    assert builder.lockfile == load_lockfile()
    assert builder.sample_dir == tmp_path / "sample_data"
    assert builder.seed_dir == tmp_path / "seeds"
    assert builder.builder_version == __version__
    assert set(builder.parsers) == {SourceId.SRI_TAX, SourceId.BCE_CNT, SourceId.INEC_CPI}
    builder.fetcher.close()


def test_build_container_selects_the_sample_fetcher_strategy(tmp_path: Path) -> None:
    settings = Settings(home=tmp_path / "home", mode="sample")

    container = build_container(settings)

    assert isinstance(container.source_fetcher, SampleSourceFetcher)
    assert isinstance(container.download_fetcher, HttpSourceFetcher)
    assert container.load_raw.warehouse is container.warehouse
    assert container.warehouse.path == settings.home / "warehouse.duckdb"
    container.close()
    assert (settings.home / "warehouse.duckdb").exists()


def test_build_container_selects_the_http_fetcher_strategy_in_full_mode(
    tmp_path: Path,
) -> None:
    settings = Settings(home=tmp_path / "home", mode="full")

    container = build_container(settings)

    assert isinstance(container.source_fetcher, HttpSourceFetcher)
    assert isinstance(container.download_fetcher, HttpSourceFetcher)
    container.close()
