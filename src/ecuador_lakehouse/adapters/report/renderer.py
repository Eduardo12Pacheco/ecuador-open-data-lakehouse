"""Jinja2 adapter that renders the self-contained static report site (S16).

The renderer owns presentation: it turns the JSON-ready snapshot into the four
page datasets, copies the vendored assets and writes plain HTML files that also
work from ``file://``. No template ever references a remote asset.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ecuador_lakehouse.domain.report import ReportSnapshot

NAV_ITEMS = (
    ("index", "Overview"),
    ("tax", "Tax collection"),
    ("prices", "Prices"),
    ("macro", "Macro & GDP"),
    ("quality", "Data quality"),
    ("sources", "Sources & lineage"),
)

_MONTHS_PER_YEAR = 12
_REFERENCE_YEAR = 2020

_TEST_LAYER_ORDER = {
    "staging": 0,
    "intermediate": 1,
    "marts": 2,
    "reconciliation": 3,
    "seeds": 4,
    "unit": 5,
    "other": 6,
}


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def _years(rows: tuple[Mapping[str, object], ...], key: str) -> list[int]:
    return sorted({int(str(row[key])) for row in rows if row.get(key) is not None})


def _overview(snapshot: ReportSnapshot) -> dict[str, object]:
    months: dict[str, dict[str, object]] = {}
    month_counts: dict[int, set[int]] = {}
    year_totals: dict[int, float] = {}
    for row in snapshot.tax_monthly:
        date = str(row["period_date"])
        year = int(str(row["period_year"]))
        month = int(str(row["period_month"]))
        nominal = _as_float(row.get("nominal_usd")) or 0.0
        real = _as_float(row.get("real_usd_2014"))
        entry = months.setdefault(
            date,
            {"date": date, "year": year, "month": month, "nominal_usd": 0.0, "real_usd": 0.0},
        )
        entry["nominal_usd"] = (_as_float(entry["nominal_usd"]) or 0.0) + nominal
        if real is None:
            entry["real_usd"] = None
        elif entry["real_usd"] is not None:
            entry["real_usd"] = (_as_float(entry["real_usd"]) or 0.0) + real
        month_counts.setdefault(year, set()).add(month)
        year_totals[year] = year_totals.get(year, 0.0) + nominal

    full_years = sorted(
        year for year, values in month_counts.items() if len(values) == _MONTHS_PER_YEAR
    )
    latest_full = full_years[-1] if full_years else max(year_totals, default=0)
    previous = year_totals.get(latest_full - 1)
    current = year_totals.get(latest_full, 0.0)
    yoy = (current - previous) / previous if previous else None

    national_general = [
        row
        for row in snapshot.inflation
        if row.get("price_area_name") == "Nacional" and row.get("level") == "general"
    ]
    latest_inflation = max(national_general, key=lambda row: str(row["period_date"]), default=None)
    ratio_2020 = next(
        (row for row in snapshot.tax_to_gdp if int(str(row["period_year"])) == _REFERENCE_YEAR),
        None,
    )
    tests_total = len(snapshot.quality_tests)
    tests_passed = sum(1 for row in snapshot.quality_tests if row.get("passed") is True)
    return {
        "mode": snapshot.mode,
        "kpis": {
            "latest_full_year": latest_full,
            "latest_full_year_total_usd": current,
            "latest_full_year_yoy": yoy,
            "inflation_dec_2024": _as_float(latest_inflation.get("yoy"))
            if latest_inflation is not None
            else None,
            "ratio_2020": _as_float(ratio_2020.get("ratio")) if ratio_2020 is not None else None,
            "tests_passed": tests_passed,
            "tests_total": tests_total,
            "tests_failed": tests_total - tests_passed,
            "batches": len(snapshot.batches),
        },
        "monthly": [months[key] for key in sorted(months)],
    }


def _tax(snapshot: ReportSnapshot) -> dict[str, object]:
    groups = sorted({str(row["tax_group_name"]) for row in snapshot.tax_monthly})
    years = _years(snapshot.tax_monthly, "period_year")
    monthly = [
        {
            "date": str(row["period_date"]),
            "year": int(str(row["period_year"])),
            "group": str(row["tax_group_name"]),
            "nominal_usd": _as_float(row.get("nominal_usd")) or 0.0,
            "real_usd": _as_float(row.get("real_usd_2014")),
        }
        for row in snapshot.tax_monthly
    ]
    provinces: dict[str, list[dict[str, object]]] = {}
    for row in snapshot.tax_provinces:
        year = str(row["period_year"])
        provinces.setdefault(year, []).append(
            {
                "name": str(row["province_name"]),
                "collected_usd": _as_float(row.get("collected_usd")) or 0.0,
            }
        )
    for rows in provinces.values():
        rows.sort(key=lambda item: float(str(item["collected_usd"])), reverse=True)
    return {
        "years": years,
        "groups": groups,
        "monthly": monthly,
        "top_lines": [
            {
                "tax_name": str(row["tax_name"]),
                "tax_group_name": str(row["tax_group_name"]),
                "total_collected_usd": _as_float(row.get("total_collected_usd")) or 0.0,
                "first_year": int(str(row["first_year"])),
                "last_year": int(str(row["last_year"])),
                "current_status": str(row["current_status"]),
            }
            for row in snapshot.tax_lifecycle
        ],
        "provinces": provinces,
    }


def _prices(snapshot: ReportSnapshot) -> dict[str, object]:
    general = [row for row in snapshot.inflation if row.get("level") == "general"]
    divisions = [row for row in snapshot.inflation if row.get("level") == "division"]
    areas = sorted({str(row["price_area_name"]) for row in general})
    areas.sort(key=lambda name: (name != "Nacional", name))
    series = [
        {
            "area": str(row["price_area_name"]),
            "date": str(row["period_date"]),
            "index_value": _as_float(row.get("index_value")),
            "yoy": _as_float(row.get("yoy")),
            "mom": _as_float(row.get("mom")),
        }
        for row in general
    ]
    latest_month = max((str(row["date"]) for row in series), default="")[:7]
    latest_division_date = max((str(row["period_date"]) for row in divisions), default=latest_month)
    return {
        "latest_month": latest_month,
        "areas": areas,
        "series": series,
        "divisions": [
            {
                "area": str(row["price_area_name"]),
                "name": str(row["ccif_name"]),
                "date": str(row["period_date"]),
                "yoy": _as_float(row.get("yoy")),
                "mom": _as_float(row.get("mom")),
            }
            for row in divisions
            if str(row["period_date"]) == latest_division_date
        ],
    }


def _macro(snapshot: ReportSnapshot) -> dict[str, object]:
    industries = [
        {
            "year": int(str(row["year"])),
            "name": str(row["name"]),
            "value_usd": _as_float(row.get("value_usd")) or 0.0,
        }
        for row in snapshot.gdp_industries
    ]
    years = sorted({int(str(row["year"])) for row in industries})
    return {
        "years": years,
        "industries": industries,
        "ratios": [
            {
                "year": int(str(row["period_year"])),
                "sri_usd": _as_float(row.get("sri_collection_usd")) or 0.0,
                "gdp_usd": _as_float(row.get("gdp_current_usd")),
                "ratio": _as_float(row.get("ratio")),
                "quarters_available": int(str(row.get("quarters_available", 0))),
                "months_available": int(str(row.get("months_available", 0))),
                "is_complete": row.get("is_complete") is True,
            }
            for row in snapshot.tax_to_gdp
        ],
    }


def _quality(snapshot: ReportSnapshot) -> dict[str, object]:
    layers: dict[str, dict[str, int]] = {}
    for row in snapshot.quality_tests:
        layer = str(row.get("layer", "other"))
        entry = layers.setdefault(layer, {"total": 0, "passed": 0, "failed": 0})
        entry["total"] += 1
        if row.get("passed") is True:
            entry["passed"] += 1
        else:
            entry["failed"] += 1
    ordered = sorted(layers.items(), key=lambda item: (_TEST_LAYER_ORDER.get(item[0], 99), item[0]))
    tests_passed = sum(1 for row in snapshot.quality_tests if row.get("passed") is True)
    return {
        "tests": {
            "total": len(snapshot.quality_tests),
            "passed": tests_passed,
            "failed": len(snapshot.quality_tests) - tests_passed,
            "layers": [
                {
                    "layer": layer,
                    "total": values["total"],
                    "passed": values["passed"],
                    "failed": values["failed"],
                }
                for layer, values in ordered
            ],
        },
        "batches": [
            {
                "batch_id": str(row.get("batch_id", "")),
                "source_id": str(row.get("source_id", "")),
                "partition": str(row.get("partition_key", row.get("partition", ""))),
                "rows": int(str(row.get("row_count", row.get("rows", 0)))),
                "status": str(row.get("status", "")),
                "loaded_at": str(row.get("loaded_at", "")),
            }
            for row in snapshot.batches
        ],
        "row_counts": [
            {
                "layer": str(row.get("layer", "")),
                "table": str(row.get("table", "")),
                "rows": int(str(row.get("rows", 0))),
            }
            for row in snapshot.row_counts
        ],
    }


def _sources(snapshot: ReportSnapshot) -> dict[str, object]:
    files = sorted(
        snapshot.sources,
        key=lambda row: (str(row.get("source_id", "")), str(row.get("partition", ""))),
    )
    return {
        "files": [dict(row) for row in files],
        "licenses": dict(snapshot.licenses),
        "checked_at": snapshot.checked_at,
    }


def _json_for_html(payload: object) -> str:
    """Serialize JSON for an inline script without ever closing the tag."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


class JinjaReportRenderer:
    """``ReportRenderer`` backed by packaged Jinja2 templates and local assets."""

    def __init__(self, *, template_dir: Path | None = None, assets_dir: Path | None = None) -> None:
        base = Path(__file__).resolve().parent
        self._template_dir = Path(template_dir) if template_dir is not None else base / "templates"
        self._assets_dir = Path(assets_dir) if assets_dir is not None else base / "assets"
        self._environment = Environment(
            loader=FileSystemLoader(str(self._template_dir)),
            autoescape=select_autoescape(("html", "j2")),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, snapshot: ReportSnapshot, site_dir: Path) -> Path:
        """Write every page and asset under ``site_dir`` and return ``index.html``."""
        site = Path(site_dir)
        site.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self._assets_dir, site / "assets", dirs_exist_ok=True)

        pages = {
            "index": (
                "overview.html.j2",
                "Overview",
                "Overview",
                "Taxes and prices at a glance",
                "A reproducible read of Ecuadorian tax collection, consumer prices and national "
                "accounts, built offline with DuckDB and dbt.",
                _overview(snapshot),
            ),
            "tax": (
                "tax.html.j2",
                "Tax collection",
                "Tax collection",
                "Who collects what, when",
                "Monthly SRI collection by tax group, province and tax line.",
                _tax(snapshot),
            ),
            "prices": (
                "prices.html.j2",
                "Prices",
                "Consumer prices",
                "How prices moved across Ecuador",
                "National CPI and division-level inflation for the December-2024 vintage.",
                _prices(snapshot),
            ),
            "macro": (
                "macro.html.j2",
                "Macro & GDP",
                "Macro & GDP",
                "Industry composition and fiscal weight",
                "Current-price national accounts and the SRI-to-GDP ratio where "
                "coverage is complete.",
                _macro(snapshot),
            ),
            "quality": (
                "quality.html.j2",
                "Data quality",
                "Data quality",
                "The quality gate, made visible",
                "Tests, row counts and the batch ledger that back every published number.",
                _quality(snapshot),
            ),
            "sources": (
                "sources.html.j2",
                "Sources & lineage",
                "Sources & lineage",
                "Where the data comes from",
                "Licenses, pinned checksums and the generated dbt documentation.",
                _sources(snapshot),
            ),
            "empty": (
                "empty.html.j2",
                "Empty state",
                "Report",
                "Nothing to show yet",
                "This is the explicit empty state used when no report data is available.",
                {"message": "No data available", "mode": snapshot.mode},
            ),
        }
        nav_items = [
            {
                "href": f"{page_name}.html",
                "label": label,
                "active": page_name == "index",
            }
            for page_name, label in NAV_ITEMS
        ]
        for page_name, (template_name, title, eyebrow, heading, lede, payload) in pages.items():
            document = self._environment.get_template(template_name).render(
                page=page_name,
                title=title,
                eyebrow=eyebrow,
                heading=heading,
                lede=lede,
                data_json=_json_for_html(payload),
                mode_label="Sample data" if snapshot.mode == "sample" else "Full data",
                nav_items=[
                    {
                        "href": item["href"],
                        "label": item["label"],
                        "active": item["href"] == f"{page_name}.html",
                    }
                    for item in nav_items
                ],
            )
            (site / f"{page_name}.html").write_text(document, encoding="utf-8")
        return site / "index.html"
