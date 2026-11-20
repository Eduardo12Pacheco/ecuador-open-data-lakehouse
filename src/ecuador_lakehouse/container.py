"""Composition root: wires settings, adapters and application use cases.

Only this module (and the CLI entry point) may know every layer; the wiring is
kept explicit instead of using a dependency-injection framework.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from ecuador_lakehouse import __version__
from ecuador_lakehouse.adapters.artifact.publisher import DuckDbArtifactPublisher
from ecuador_lakehouse.adapters.artifact.verifier import DuckDbArtifactVerifier
from ecuador_lakehouse.adapters.docs.lineage_mermaid import LineageMermaidRenderer
from ecuador_lakehouse.adapters.parsers.bce_cnt import BceCntParser
from ecuador_lakehouse.adapters.parsers.inec_cpi import InecCpiParser
from ecuador_lakehouse.adapters.parsers.sri_tax import SriTaxParser
from ecuador_lakehouse.adapters.report.reader import DuckDbReportReader
from ecuador_lakehouse.adapters.report.renderer import JinjaReportRenderer
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
    PublishStep,
    QualityStep,
    ReportStep,
    TransformStep,
)
from ecuador_lakehouse.application.use_cases.publish import CheckContract, PublishArtifact
from ecuador_lakehouse.application.use_cases.verify import VerifyArtifact
from ecuador_lakehouse.config import Settings, get_settings
from ecuador_lakehouse.domain.contract import ArtifactContract
from ecuador_lakehouse.domain.dag import Dag, Step
from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.manifest import FileRef, SourceRef
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
        Step("publish", ("quality",)),
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
    publish_artifact: PublishArtifact
    pipeline_acquire: AcquireSources
    pipeline: PipelineRunner

    def close(self) -> None:
        """Release network resources, the warehouse lock and any other adapter."""
        self.download_fetcher.close()
        self.source_fetcher.close()
        self.license_catalog.close()
        self.warehouse.close()
        self.transformer.close()


def build_container(
    settings: Settings | None = None, *, publish_out: Path | None = None
) -> Container:
    """Build the container from explicit settings or the process environment.

    ``publish_out`` enables the ``publish`` step in the default build selection;
    the step always exists in the DAG so ``--select publish`` keeps working.
    """
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
        reader=DuckDbReportReader(
            warehouse_path=resolved.home / "warehouse.duckdb",
            dbt_target_dir=transformer.target_dir,
        ),
        renderer=JinjaReportRenderer(),
        lockfile=lockfile,
        site_dir=resolved.home / "site",
        mode=resolved.mode,
    )
    pipeline_acquire = AcquireSources(fetcher=source_fetcher, lockfile=lockfile)
    artifact_out = publish_out if publish_out is not None else resolved.home / "artifact"
    publish_artifact = PublishArtifact(
        store=DuckDbArtifactPublisher(),
        transformer=transformer,
        contract=load_artifact_contract(),
        warehouse_path=resolved.home / "warehouse.duckdb",
        out_dir=artifact_out,
        built_from=build_provenance(resolved, lockfile),
        generator=f"ecuador-open-data-lakehouse/{__version__}",
        data_mode=resolved.mode,
        attribution=load_attribution(),
    )
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
        "publish": PublishStep(publish_artifact=publish_artifact, warehouse=warehouse).execute,
    }
    default_steps = (
        None
        if publish_out is not None
        else frozenset(step.name for step in PIPELINE_DAG.steps) - {"publish"}
    )
    pipeline = PipelineRunner(
        PIPELINE_DAG,
        steps,
        warehouse,
        mode=resolved.mode,
        idempotent_steps=frozenset({"acquire"}),
        default_steps=default_steps,
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
        publish_artifact=publish_artifact,
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


def load_artifact_contract(path: Path | None = None) -> ArtifactContract:
    """Load the committed artifact contract (packaged by default)."""
    try:
        text = (
            path.read_text(encoding="utf-8")
            if path is not None
            else resources.files("ecuador_lakehouse")
            .joinpath("artifact_contract.json")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, OSError) as exc:
        raise ConfigError("artifact contract is missing or unreadable") from exc
    return ArtifactContract.from_json_text(text)


def load_attribution() -> str:
    """Load the attribution text that ships with every published artifact."""
    return (
        resources.files("ecuador_lakehouse")
        .joinpath("sample_data", "ATTRIBUTION.md")
        .read_text(encoding="utf-8")
    )


def build_provenance(settings: Settings, lockfile: Lockfile) -> tuple[SourceRef, ...]:
    """Record the exact files each source contributed to the published artifact."""
    sample = load_sample_manifest() if settings.mode == "sample" else None
    refs: list[SourceRef] = []
    for source_id in (SourceId.SRI_TAX, SourceId.BCE_CNT, SourceId.INEC_CPI):
        locked = [entry for entry in lockfile.files if entry.source_id is source_id]
        if not locked:
            continue
        if sample is not None:
            files = tuple(
                FileRef(name=entry.name, sha256=entry.sha256)
                for entry in sample.by_source(source_id)
            )
        else:
            files = tuple(FileRef(name=entry.filename, sha256=entry.sha256) for entry in locked)
        if not files:
            continue
        license_id = lockfile.licenses.get(source_id.value)
        if not license_id:
            raise ConfigError(f"lockfile has no license for source {source_id.value!r}")
        refs.append(
            SourceRef(
                source_id=source_id,
                url=locked[0].url,
                license_id=license_id,
                files=files,
            )
        )
    return tuple(refs)


def build_artifact_verifier() -> VerifyArtifact:
    """Compose the verify use case without creating a warehouse file."""
    return VerifyArtifact(store=DuckDbArtifactVerifier())


def build_contract_checker(contract_path: Path | None = None) -> CheckContract:
    """Compose the contract checker around the committed or supplied contract."""
    return CheckContract(
        store=DuckDbArtifactPublisher(), contract=load_artifact_contract(contract_path)
    )
