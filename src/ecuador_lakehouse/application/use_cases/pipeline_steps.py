"""Pipeline steps: thin application use cases wired into the DAG runner (S13).

Every step implements the same contract: receive a :class:`StepContext`, do one
job through ports, publish its typed output for the next step and return a
:class:`StepResult` with numeric metrics. The runner owns ordering, retries and
the run ledger; the steps own only the work.

Steps that drive dbt close the warehouse first: DuckDB allows a single writer,
so dbt gets exclusive access to the file (D18). The report step reopens it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ecuador_lakehouse.application.pipeline import StepContext
from ecuador_lakehouse.application.ports import FetchResult, Transformer, Warehouse
from ecuador_lakehouse.application.use_cases.acquire import AcquireSources
from ecuador_lakehouse.application.use_cases.build_docs import BuildDocs
from ecuador_lakehouse.application.use_cases.build_report import BuildReport
from ecuador_lakehouse.application.use_cases.load_raw import LoadRaw
from ecuador_lakehouse.application.use_cases.publish import PublishArtifact
from ecuador_lakehouse.domain.batches import BatchStatus
from ecuador_lakehouse.domain.errors import QualityGateError
from ecuador_lakehouse.domain.quality import QualitySummary
from ecuador_lakehouse.domain.runs import StepResult, StepStatus
from ecuador_lakehouse.domain.sources import Lockfile, SourceId


def _result(name: str, detail: str, **metrics: int) -> StepResult:
    return StepResult(
        name=name,
        status=StepStatus.OK,
        duration_s=0.0,
        detail=detail,
        metrics=metrics,
    )


@dataclass(frozen=True, slots=True)
class AcquireStep:
    """Fetch every pinned partition of every source for the configured years."""

    acquire_sources: AcquireSources
    lockfile: Lockfile
    years: tuple[int, ...]

    def execute(self, context: StepContext) -> StepResult:
        """Acquire all sources and publish the fetched files to the context."""
        selected_years = {str(year) for year in self.years}
        acquired: list[FetchResult] = []
        for source_id in (SourceId.SRI_TAX, SourceId.BCE_CNT, SourceId.INEC_CPI):
            partitions = [
                source_file.partition
                for source_file in self.lockfile.files
                if source_file.source_id is source_id
                and (source_id is not SourceId.SRI_TAX or source_file.partition in selected_years)
            ]
            if partitions:
                acquired.extend(self.acquire_sources.execute(source_id, partitions))
        context.outputs["acquire"] = tuple(acquired)
        return _result("acquire", f"{len(acquired)} partitions acquired", fetched=len(acquired))


@dataclass(frozen=True, slots=True)
class LoadRawStep:
    """Parse the acquired files and load them into the raw layer."""

    load_raw: LoadRaw

    def execute(self, context: StepContext) -> StepResult:
        """Load the files published by ``acquire`` and report ledger outcomes."""
        fetched = context.output("acquire")
        results = self.load_raw.execute(list(fetched))
        counts = {
            BatchStatus.LOADED.value: 0,
            BatchStatus.SKIPPED.value: 0,
            BatchStatus.REPLACED.value: 0,
        }
        for result in results:
            counts[result.status.value] += 1
        detail = (
            f"{counts['loaded']} loaded, {counts['skipped']} skipped, {counts['replaced']} replaced"
        )
        context.outputs["load_raw"] = tuple(results)
        return _result("load_raw", detail, **counts)


@dataclass(frozen=True, slots=True)
class TransformStep:
    """Seed reference data and build every dbt model."""

    transformer: Transformer
    warehouse: Warehouse

    def execute(self, context: StepContext) -> StepResult:
        """Run dbt with exclusive access to the warehouse file."""
        self.warehouse.close()
        try:
            self.transformer.seed_and_run()
        finally:
            self.warehouse.open()
        return _result("transform", "dbt seed + run completed")


@dataclass(frozen=True, slots=True)
class QualityStep:
    """Run the dbt data and unit tests, closing the gate on any failure."""

    transformer: Transformer
    warehouse: Warehouse

    def execute(self, context: StepContext) -> StepResult:
        """Run the quality gate and publish its summary."""
        self.warehouse.close()
        try:
            summary = self.transformer.test()
        finally:
            self.warehouse.open()
        context.outputs["quality"] = summary
        detail = f"{summary.passed}/{summary.total} tests passed"
        metrics = {"tests_total": summary.total, "tests_passed": summary.passed}
        if not summary.ok:
            failed = ", ".join(summary.failed_names)
            raise QualityGateError(f"quality gate failed ({summary.failed} failed): {failed}")
        return _result("quality", detail, **metrics)


@dataclass(frozen=True, slots=True)
class DocsStep:
    """Generate static dbt docs into the report site."""

    build_docs: BuildDocs
    warehouse: Warehouse

    def execute(self, context: StepContext) -> StepResult:
        """Run dbt docs generate with exclusive access to the warehouse file."""
        self.warehouse.close()
        try:
            result = self.build_docs.execute()
        finally:
            self.warehouse.open()
        context.outputs["docs"] = result
        return _result("docs", f"static docs at {result.site_index.name}")


@dataclass(frozen=True, slots=True)
class ReportStep:
    """Write the machine-readable report data consumed by the static UI."""

    build_report: BuildReport

    def execute(self, context: StepContext) -> StepResult:
        """Reopen the warehouse and write the report payload."""
        result = self.build_report.execute()
        context.outputs["report"] = result
        return _result(
            "report", f"{result.batch_count} batches described", batches=result.batch_count
        )


@dataclass(frozen=True, slots=True)
class PublishStep:
    """Publish the marts as a versioned, verifiable artifact."""

    publish_artifact: PublishArtifact
    warehouse: Warehouse

    def execute(self, context: StepContext) -> StepResult:
        """Reuse the quality summary of this run, or run the gate when selected alone."""
        summary = context.outputs.get("quality")
        quality = summary if isinstance(summary, QualitySummary) else None
        self.warehouse.close()
        try:
            result = self.publish_artifact.execute(quality=quality)
        finally:
            self.warehouse.open()
        context.outputs["publish"] = result
        return _result(
            "publish",
            f"{result.table_count} tables at {result.artifact_dir.name}",
            tables=result.table_count,
        )
