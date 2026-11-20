"""Composition root: wires settings, adapters and application use cases.

Only this module (and the CLI entry point) may know every layer; the wiring is
kept explicit instead of using a dependency-injection framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from ecuador_lakehouse import __version__
from ecuador_lakehouse.adapters.parsers.bce_cnt import BceCntParser
from ecuador_lakehouse.adapters.parsers.inec_cpi import InecCpiParser
from ecuador_lakehouse.adapters.parsers.sri_tax import SriTaxParser
from ecuador_lakehouse.adapters.sources.ckan_catalog import CkanCatalog
from ecuador_lakehouse.adapters.sources.http_fetcher import HttpSourceFetcher
from ecuador_lakehouse.adapters.sources.sample_fetcher import SampleSourceFetcher
from ecuador_lakehouse.application.ports import LicenseCatalog, SourceFetcher, SourceParser
from ecuador_lakehouse.application.use_cases.acquire import AcquireSources
from ecuador_lakehouse.application.use_cases.build_sample import BuildSample
from ecuador_lakehouse.config import Settings, get_settings
from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sample import SampleManifest
from ecuador_lakehouse.domain.sources import Lockfile, SourceId


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


def package_path(*parts: str) -> Path:
    """Return a filesystem path to a packaged resource (editable installs and wheels)."""
    return Path(str(resources.files("ecuador_lakehouse").joinpath(*parts)))


def load_sample_manifest() -> SampleManifest:
    """Load and validate the manifest of the bundled offline sample."""
    return SampleSourceFetcher.load_manifest()


def default_parsers() -> dict[SourceId, SourceParser]:
    """Compose the parser Strategy registry keyed by source."""
    return {
        SourceId.SRI_TAX: SriTaxParser(),
        SourceId.BCE_CNT: BceCntParser(),
        SourceId.INEC_CPI: InecCpiParser(),
    }


def build_sample_builder(
    settings: Settings,
    *,
    cache_dir: Path | None = None,
    output_dir: Path | None = None,
    seed_dir: Path | None = None,
) -> BuildSample:
    """Wire the maintainer sample builder (network fetcher + parser registry)."""
    fetcher = HttpSourceFetcher(
        settings.home,
        cache_dir=cache_dir,
        timeout_s=settings.http_timeout_s,
        retries=settings.http_retries,
    )
    return BuildSample(
        fetcher=fetcher,
        lockfile=load_lockfile(),
        parsers=default_parsers(),
        sample_dir=output_dir if output_dir is not None else package_path("sample_data"),
        seed_dir=seed_dir if seed_dir is not None else package_path("dbt_project", "seeds"),
        builder_version=__version__,
    )


def verify_sample_integrity(settings: Settings) -> int:
    """Verify every bundled sample file against its manifest and return the count."""
    fetcher = SampleSourceFetcher(
        load_sample_manifest(),
        settings.home / "cache",
    )
    return fetcher.verify_all()
