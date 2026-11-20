"""Typed snapshot of the marts consumed by the static report UI (S16).

The report adapter reads DuckDB and hands the application a frozen snapshot of
plain JSON-compatible rows. Keeping this contract in the domain means the
application never executes SQL and the renderer never opens the warehouse.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

Row = Mapping[str, object]


def _rows(value: Iterable[Row] | None) -> tuple[Row, ...]:
    return tuple(dict(row) for row in (value or ()))


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    """Every dataset one generated report site needs, already aggregated."""

    mode: str = "sample"
    tax_monthly: tuple[Row, ...] = ()
    tax_lifecycle: tuple[Row, ...] = ()
    tax_provinces: tuple[Row, ...] = ()
    inflation: tuple[Row, ...] = ()
    gdp_industries: tuple[Row, ...] = ()
    tax_to_gdp: tuple[Row, ...] = ()
    quality_tests: tuple[Row, ...] = ()
    batches: tuple[Row, ...] = ()
    row_counts: tuple[Row, ...] = ()
    sources: tuple[Row, ...] = ()
    licenses: Mapping[str, str] = field(default_factory=dict)
    checked_at: str = ""

    def __post_init__(self) -> None:
        if self.mode not in {"sample", "full"}:
            raise ValueError(f"unknown data mode: {self.mode!r}")
        for name in (
            "tax_monthly",
            "tax_lifecycle",
            "tax_provinces",
            "inflation",
            "gdp_industries",
            "tax_to_gdp",
            "quality_tests",
            "batches",
            "row_counts",
            "sources",
        ):
            object.__setattr__(self, name, _rows(getattr(self, name)))
        object.__setattr__(self, "licenses", dict(self.licenses))

    def with_sources(
        self,
        sources: tuple[Row, ...],
        *,
        licenses: Mapping[str, str],
        checked_at: str,
    ) -> ReportSnapshot:
        """Return a copy carrying the pinned source inventory and licenses."""
        return ReportSnapshot(
            mode=self.mode,
            tax_monthly=self.tax_monthly,
            tax_lifecycle=self.tax_lifecycle,
            tax_provinces=self.tax_provinces,
            inflation=self.inflation,
            gdp_industries=self.gdp_industries,
            tax_to_gdp=self.tax_to_gdp,
            quality_tests=self.quality_tests,
            batches=self.batches,
            row_counts=self.row_counts,
            sources=sources,
            licenses=licenses,
            checked_at=checked_at,
        )
