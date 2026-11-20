"""Composition root: wires settings, adapters and application use cases.

Only this module (and the CLI entry point) may know every layer; the wiring is
kept explicit instead of using a dependency-injection framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from ecuador_lakehouse import __version__
from ecuador_lakehouse.adapters.docs.lineage_mermaid import LineageMermaidRenderer
from ecuador_lakehouse.adapters.parsers.bce_cnt import BceCntParser
from ecuador_lakehouse.adapters.parsers.inec_cpi import InecCpiParser
from ecuador_lakehouse.adapters.parsers.sri_tax import SriTaxParser
from ecuador_lakehouse.adapters.sources.ckan_catalog import CkanCatalog
from ecuador_lakehouse.adapters.sources.http_fetcher import HttpSourceFetcher
from ecuador_lakehouse.adapters.sources.sample_fetcher import SampleSourceFetcher
from ecuador_lakehouse.adapters.transform.dbt_runner import DbtTransformer
from ecuador_lakehouse.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from ecuador_lakehouse.application.pipeline import PipelineRunner, RetryPolicy
from ecuador_lakehouse.application.ports import (
    LicenseCatalog,
    SourceFetcher,
    SourceParser,
    Warehouse,
)
from ecuador_lakehouse.application.use_cases.acquire import AcquireSources
from ecuador_lakehouse.application.use_cases.build_docs import BuildDocs
from ecuador_lakehouse.application.use_cases.build_report import BuildReport
from ecuador_lakehouse.application.use_cases.build_sample import BuildSample
from ecuador_lakehouse.application.use_cases.load_raw import LoadRaw
from ecuador_lakehouse.application.use_cases.pipeline_steps import (
    AcquireStep,
    DocsStep,
    LoadRawStep,
    QualityStep,
    ReportStep,
    TransformStep,
)
from ecuador_lakehouse.config import Settings, get_settings
from ecuador_lakehouse.domain.dag import Dag, Step
from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sample import SampleManifest
from ecuador_lakehouse.domain.sources import Lockfile, SourceId

PIPELINE_DAG = Dag(
    [
        Step("acquire"),
        Step("load_raw", ("acquire",)),
        Step("transform", ("load_raw",)),
        Step("quality", ("transform",)),
        Step("docs", ("quality",)),
        Step("report", ("docs",)),
    ]
)


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
    download_fetcher: SourceFetcher
    license_catalog: LicenseCatalog
    acquire_sources: AcquireSources
    source_fetcher: SourceFetcher
    warehouse: Warehouse
    load_raw: LoadRaw
    transformer: DbtTransformer
    build_docs: BuildDocs
    build_report: BuildReport
    pipeline_acquire: AcquireSources
    pipeline: PipelineRunner

    def close(self) -> None:
        """Release network resources, the warehouse lock and any other adapter."""
        self.download_fetcher.close()
        self.source_fetcher.close()
        self.license_catalog.close()
        self.warehouse.close()
        self.transformer.close()


def build_container(settings: Settings | None = None) -> Container:
    """Build the container from explicit settings or the process environment."""
    resolved = settings if settings is not None else get_settings()
    lockfile = load_lockfile()
    download_fetcher = HttpSourceFetcher(
        resolved.home,
        timeout_s=resolved.http_timeout_s,
        retries=resolved.http_retries,
    )
    source_fetcher = build_source_fetcher(resolved)
    license_catalog = CkanCatalog(timeout_s=resolved.http_timeout_s)
    warehouse = DuckDbWarehouse(
        resolved.home / "warehouse.duckdb",
        mode=resolved.mode,
    )
    transformer = DbtTransformer(
        warehouse_path=resolved.home / "warehouse.duckdb",
        home=resolved.home,
        threads=resolved.dbt_threads,
    )
    parsers = default_parsers()
    load_raw = LoadRaw(parsers=parsers, warehouse=warehouse)
    build_docs = BuildDocs(
        transformer=transformer,
        renderer=LineageMermaidRenderer(),
        site_dir=resolved.home / "site",
    )
    build_report = BuildReport(
        warehouse=warehouse,
        site_dir=resolved.home / "site",
        mode=resolved.mode,
    )
    pipeline_acquire = AcquireSources(fetcher=source_fetcher, lockfile=lockfile)
    steps = {
        "acquire": AcquireStep(
            acquire_sources=pipeline_acquire,
            lockfile=lockfile,
            years=resolved.years,
        ).execute,
        "load_raw": LoadRawStep(load_raw=load_raw).execute,
        "transform": TransformStep(transformer=transformer, warehouse=warehouse).execute,
        "quality": QualityStep(transformer=transformer, warehouse=warehouse).execute,
        "docs": DocsStep(build_docs=build_docs, warehouse=warehouse).execute,
        "report": ReportStep(build_report=build_report).execute,
    }
    pipeline = PipelineRunner(
        PIPELINE_DAG,
        steps,
        warehouse,
        mode=resolved.mode,
        idempotent_steps=frozenset({"acquire"}),
        retry_policies={"acquire": RetryPolicy(max_attempts=3, delay_s=0.5)},
    )
    return Container(
        settings=resolved,
        lockfile=lockfile,
        download_fetcher=download_fetcher,
        license_catalog=license_catalog,
        acquire_sources=AcquireSources(fetcher=download_fetcher, lockfile=lockfile),
        source_fetcher=source_fetcher,
        warehouse=warehouse,
        load_raw=load_raw,
        transformer=transformer,
        build_docs=build_docs,
        build_report=build_report,
        pipeline_acquire=pipeline_acquire,
        pipeline=pipeline,
    )


def build_source_fetcher(settings: Settings) -> SourceFetcher:
    """Select the acquisition Strategy for the configured mode (S2, S4)."""
    if settings.mode == "sample":
        return SampleSourceFetcher(load_sample_manifest(), settings.home / "cache")
    return HttpSourceFetcher(
        settings.home,
        timeout_s=settings.http_timeout_s,
        retries=settings.http_retries,
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
