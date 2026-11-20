"""Browser end-to-end tests for the six report pages (S16, T13)."""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, Route

from tests.e2e.conftest import ReportHome

pytestmark = pytest.mark.e2e


READY = 'html[data-ready="true"]'

PAGES = (
    ("index", "Overview"),
    ("tax", "Tax collection"),
    ("prices", "Prices"),
    ("macro", "Macro & GDP"),
    ("quality", "Data quality"),
    ("sources", "Sources & lineage"),
)

CHART_PAGES = ("index", "tax", "prices", "macro")

_DATA_INDEX = re.compile(r'<script type="application/json" id="data-index">.*?</script>', re.DOTALL)


def _open(page: Page, report: ReportHome, name: str) -> None:
    response = page.goto(f"{report.url}/{name}.html", wait_until="load")
    assert response is not None
    assert response.ok
    page.wait_for_selector(READY)
    page.wait_for_timeout(250)


def _visible_text(page: Page, selector: str) -> str:
    assert page.locator(selector).count() >= 1
    return page.locator(selector).first.inner_text().strip()


@pytest.mark.parametrize(("name", "title"), PAGES)
def test_every_page_loads_without_console_errors(
    page: Page,
    report: ReportHome,
    console_errors: list[str],
    name: str,
    title: str,
) -> None:
    _open(page, report, name)

    assert page.title() == f"{title} | Ecuador Open Data Lakehouse"
    assert _visible_text(page, "h1")
    assert page.locator("#error-banner").is_hidden()
    assert page.locator("body").get_attribute("data-page") == name
    assert console_errors == []


@pytest.mark.parametrize("name", CHART_PAGES)
def test_each_chart_container_draws_one_canvas(
    page: Page, report: ReportHome, console_errors: list[str], name: str
) -> None:
    _open(page, report, name)

    charts = page.locator(".chart")
    assert charts.count() >= 1
    canvases = page.locator(".chart canvas")
    assert canvases.count() == charts.count()
    for index in range(charts.count()):
        assert charts.nth(index).locator("canvas").count() == 1
    assert console_errors == []


def test_overview_kpis_and_chart_are_populated(
    page: Page, report: ReportHome, console_errors: list[str]
) -> None:
    _open(page, report, "index")

    total = _visible_text(page, '[data-kpi="latest_full_year_total"]')
    assert total not in {"", "Pending"}
    assert total.startswith("$")
    tests_value = _visible_text(page, '[data-kpi="tests_value"]')
    passed, _, available = tests_value.partition("/")
    assert int(passed) > 0
    assert int(available) == int(passed)
    assert _visible_text(page, '[data-kpi="mode"]') == "Sample data"
    assert page.locator("#chart-overview-monthly canvas").count() == 1
    assert console_errors == []


def test_tax_page_tables_and_year_controls_are_populated(
    page: Page, report: ReportHome, console_errors: list[str]
) -> None:
    _open(page, report, "tax")

    assert page.locator("#tax-from option").count() == 10
    assert page.locator("#tax-to option").count() == 10
    assert page.locator("#tax-province-year option").count() == 10
    assert page.locator("#tax-top-lines tr").count() == 10
    assert page.locator("#chart-tax-provinces canvas").count() == 1
    assert console_errors == []


def test_tax_year_range_redraws_the_chart(
    page: Page, report: ReportHome, console_errors: list[str]
) -> None:
    _open(page, report, "tax")

    before = page.evaluate(
        """() => window.echarts
            .getInstanceByDom(document.getElementById("chart-tax-groups"))
            .getOption().xAxis[0].data"""
    )
    assert len(before) >= 100

    page.select_option("#tax-from", "2023")
    page.wait_for_timeout(250)

    after = page.evaluate(
        """() => window.echarts
            .getInstanceByDom(document.getElementById("chart-tax-groups"))
            .getOption().xAxis[0].data"""
    )
    assert len(after) < len(before)
    assert after[0].startswith("2023-01")
    assert after[-1].startswith("2026-")
    assert console_errors == []


def test_prices_page_populates_areas_divisions_and_kpi(
    page: Page, report: ReportHome, console_errors: list[str]
) -> None:
    _open(page, report, "prices")

    assert _visible_text(page, '[data-kpi="latest_month"]') == "2024-12"
    assert page.locator("#price-area option").count() == 12
    assert page.locator("#price-divisions tr").count() > 0
    page.select_option("#price-area", "Guayaquil")
    page.wait_for_timeout(250)
    assert page.locator("#price-divisions tr").count() > 0
    assert console_errors == []


def test_macro_page_populates_years_and_ratio_table(
    page: Page, report: ReportHome, console_errors: list[str]
) -> None:
    _open(page, report, "macro")

    assert page.locator("#macro-year option").count() == 22
    assert page.locator("#macro-ratios tr").count() == 10
    assert page.locator("#macro-ratios tr", has_text="Yes").count() == 4
    assert page.locator("#chart-macro-ratio canvas").count() == 1
    page.select_option("#macro-year", "2019")
    page.wait_for_timeout(250)
    assert page.locator("#chart-macro-industries canvas").count() == 1
    assert console_errors == []


def test_quality_page_populates_layers_batches_and_rows(
    page: Page, report: ReportHome, console_errors: list[str]
) -> None:
    _open(page, report, "quality")

    total = int(_visible_text(page, '[data-kpi="tests_total"]'))
    assert total >= 260
    assert page.locator("#quality-layers tr").count() >= 5
    assert page.locator("#quality-batches tr").count() == 12
    assert page.locator("#quality-rows tr").count() > 0
    assert console_errors == []


def test_sources_page_populates_licenses_and_checksums(
    page: Page, report: ReportHome, console_errors: list[str]
) -> None:
    _open(page, report, "sources")

    assert _visible_text(page, '[data-kpi="file_count"]') == "12"
    assert page.locator("#sources-files tr").count() == 12
    checksum = page.locator("#sources-files tr td.mono").first.inner_text().strip()
    assert re.fullmatch(r"[0-9a-f]{64}", checksum)
    assert page.locator("#sources-licenses tr").count() == 3
    assert console_errors == []


def test_theme_toggle_flips_and_persists_after_reload(
    page: Page, report: ReportHome, console_errors: list[str]
) -> None:
    _open(page, report, "index")
    assert page.evaluate("document.documentElement.dataset.theme") == "light"

    page.click("#theme-toggle")
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert page.evaluate("localStorage.getItem('lakehouse-theme')") == "dark"
    assert page.locator("#chart-overview-monthly canvas").count() == 1

    page.reload(wait_until="load")
    page.wait_for_selector(READY)
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert console_errors == []


def test_system_dark_scheme_applies_dark_tokens(
    page: Page, report: ReportHome, console_errors: list[str]
) -> None:
    _open(page, report, "index")
    assert page.evaluate("document.documentElement.dataset.theme") == "light"

    page.emulate_media(color_scheme="dark")
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'", timeout=5000)

    background = page.evaluate("getComputedStyle(document.body).backgroundColor")
    color = page.evaluate("getComputedStyle(document.body).color")
    assert background == "rgb(15, 20, 26)"
    assert color == "rgb(230, 237, 243)"
    assert page.locator("#chart-overview-monthly canvas").count() == 1
    assert console_errors == []


def test_tab_reaches_nav_links_with_visible_focus(page: Page, report: ReportHome) -> None:
    _open(page, report, "index")

    focused: dict[str, object] | None = None
    for _ in range(24):
        page.keyboard.press("Tab")
        candidate = page.evaluate(
            """() => {
                const el = document.activeElement;
                if (!el || el.tagName !== "A") { return null; }
                if (!el.closest("nav.site-nav")) { return null; }
                const style = getComputedStyle(el);
                return {
                    label: el.textContent.trim(),
                    focusVisible: el.matches(":focus-visible"),
                    outlineStyle: style.outlineStyle,
                    outlineWidth: style.outlineWidth,
                };
            }"""
        )
        if candidate is not None:
            focused = candidate
            break

    assert focused is not None, "Tab never reached a navigation link"
    assert str(focused["label"])
    assert focused["focusVisible"] is True
    assert focused["outlineStyle"] != "none"
    assert focused["outlineWidth"] not in {"0px", ""}


def test_empty_state_renders_without_the_data_blob(
    page: Page, report: ReportHome, console_errors: list[str]
) -> None:
    html = (report.site / "index.html").read_text(encoding="utf-8")
    body = _DATA_INDEX.sub("", html)
    assert 'id="data-index"' not in body
    page.route(
        "**/index.html",
        lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body),
    )
    page.goto(f"{report.url}/index.html", wait_until="load")
    page.wait_for_selector(READY)

    assert page.locator("#empty-state").is_visible()
    assert "No data available" in page.locator("#empty-state").inner_text()
    assert page.locator("#error-banner").is_hidden()
    assert console_errors == []


def test_error_state_renders_for_malformed_json(
    page: Page, report: ReportHome, console_errors: list[str]
) -> None:
    html = (report.site / "index.html").read_text(encoding="utf-8")
    body = _DATA_INDEX.sub(
        '<script type="application/json" id="data-index">{not valid json</script>', html
    )
    assert body != html
    page.route(
        "**/index.html",
        lambda route: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body),
    )
    page.goto(f"{report.url}/index.html", wait_until="load")
    page.wait_for_selector(READY)

    banner = page.locator("#error-banner")
    assert banner.is_visible()
    assert "could not be parsed" in banner.inner_text()
    assert page.locator("#empty-state").is_hidden()
    assert console_errors == []


@pytest.fixture(autouse=True)
def _forbid_remote_requests(page: Page) -> None:
    """Fail loudly if any page loads something that is not the local report origin."""

    def handler(route: Route) -> None:
        url = route.request.url
        if url.startswith(("http://127.0.0.1:", "http://localhost:")):
            route.continue_()
        else:
            route.abort()

    page.route("**/*", handler)
