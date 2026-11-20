"""Rich presenters shared by the pipeline commands (S13, S24).

The CLI prints tables instead of raw logs: one row per pipeline step with its
status and duration, plus a compact quality-gate line. Status words stay plain
ASCII so Windows consoles render them correctly.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from ecuador_lakehouse.application.pipeline import RunReport


def _status_text(ok: bool) -> str:
    return "ok" if ok else "FAILED"


def run_table(report: RunReport) -> Table:
    """Build the per-step summary table for one pipeline run."""
    table = Table(title="Pipeline", show_lines=False, header_style="bold")
    table.add_column("Step", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Duration", justify="right", no_wrap=True)
    table.add_column("Detail")
    for step in report.steps:
        table.add_row(
            step.name,
            _status_text(step.ok),
            f"{step.duration_s:.1f}s",
            step.detail,
        )
    table.caption = f"run {report.record.run_id} ({report.record.mode})"
    return table


def print_run(report: RunReport, console: Console | None = None) -> None:
    """Print the pipeline summary table."""
    (console or Console()).print(run_table(report))


def quality_line(report: RunReport) -> str:
    """Return the ``PASS n/m`` line for the quality step of a run."""
    metrics = report.metrics("quality")
    total = metrics.get("tests_total", 0)
    passed = metrics.get("tests_passed", 0)
    if passed == total:
        return f"PASS {passed}/{total} dbt data and unit tests"
    return f"FAIL {passed}/{total} dbt data and unit tests"


def format_run(report: RunReport) -> str:
    """Render the run table to text (used by tests and scripted callers)."""
    console = Console(file=None, width=120, force_terminal=False, color_system=None)
    with console.capture() as capture:
        console.print(run_table(report))
    return capture.get()
