"""Composition root: wires settings, adapters and application use cases.

Only this module (and the CLI entry point) may know every layer; the wiring is
kept explicit instead of using a dependency-injection framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from ecuador_lakehouse.adapters.sources.ckan_catalog import CkanCatalog
from ecuador_lakehouse.adapters.sources.http_fetcher import HttpSourceFetcher
from ecuador_lakehouse.application.ports import LicenseCatalog, SourceFetcher
from ecuador_lakehouse.application.use_cases.acquire import AcquireSources
from ecuador_lakehouse.config import Settings, get_settings
from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sources import Lockfile


def load_lockfile() -> Lockfile:
    """Read and validate the ``sources.lock.json`` shipped inside the package."""
    try:
        text = (
            resources.files("ecuador_lakehouse")
            .joinpath("sources.lock.json")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError) as exc:
        raise ConfigError("packaged sources.lock.json is missing or unreadable") from exc
    return Lockfile.from_json_text(text)


@dataclass(frozen=True, slots=True)
class Container:
    """Resolved dependencies for one CLI invocation."""

    settings: Settings
    lockfile: Lockfile
    source_fetcher: SourceFetcher
    license_catalog: LicenseCatalog
    acquire_sources: AcquireSources

    def close(self) -> None:
        """Release network resources held by the wired adapters."""
        self.source_fetcher.close()
        self.license_catalog.close()


def build_container(settings: Settings | None = None) -> Container:
    """Build the container from explicit settings or the process environment."""
    resolved = settings if settings is not None else get_settings()
    lockfile = load_lockfile()
    source_fetcher = HttpSourceFetcher(
        resolved.home,
        timeout_s=resolved.http_timeout_s,
        retries=resolved.http_retries,
    )
    license_catalog = CkanCatalog(timeout_s=resolved.http_timeout_s)
    return Container(
        settings=resolved,
        lockfile=lockfile,
        source_fetcher=source_fetcher,
        license_catalog=license_catalog,
        acquire_sources=AcquireSources(fetcher=source_fetcher, lockfile=lockfile),
    )
