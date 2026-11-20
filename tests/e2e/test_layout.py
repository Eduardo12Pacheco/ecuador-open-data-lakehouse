"""Layout quality checks for the report pages (S16, T13).

The screenshots are reviewed by a human (see the plan Log); these assertions are
the machine-checkable half of that review: no overlapping text boxes, no text
clipped by its container, legible font sizes and a configured, visible legend on
charts that carry more than one series.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import ReportHome

pytestmark = pytest.mark.e2e

READY = 'html[data-ready="true"]'
PAGES = ("index", "tax", "prices", "macro", "quality", "sources")
LEGEND_SERIES = {"index": 2, "tax": 3, "prices": 2}

_TEXT_SELECTOR = (
    "h1,h2,.lede,.eyebrow,.kpi-label,.kpi-value,.kpi-detail,.site-nav a,"
    ".theme-toggle,.brand-text strong,.brand-sub,th,td,label,.badge,.chart-note,.button"
)

_LAYOUT_SCRIPT = """
    (selector) => {
        const visible = (el) => {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" &&
                style.display !== "none" && !el.classList.contains("visually-hidden") &&
                (el.textContent || "").trim().length > 0;
        };
        const nodes = Array.from(document.querySelectorAll(selector)).filter(visible);
        const leaves = nodes.filter((node) => !nodes.some(
            (other) => other !== node && node.contains(other)
        ));
        return leaves.map((node) => {
            const rect = node.getBoundingClientRect();
            const style = getComputedStyle(node);
            return {
                text: (node.textContent || "").trim().slice(0, 40),
                left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom,
                fontSize: parseFloat(style.fontSize),
                scrollWidth: node.scrollWidth,
                clientWidth: node.clientWidth
            };
        });
    }
    """


def _open(page: Page, report: ReportHome, name: str) -> None:
    response = page.goto(f"{report.url}/{name}.html", wait_until="load")
    assert response is not None
    assert response.ok
    page.wait_for_selector(READY)
    page.wait_for_timeout(300)


@pytest.mark.parametrize("name", PAGES)
def test_no_overlapping_text_blocks(page: Page, report: ReportHome, name: str) -> None:
    _open(page, report, name)
    boxes = page.evaluate(_LAYOUT_SCRIPT, _TEXT_SELECTOR)
    assert boxes

    overlaps: list[str] = []
    for index, first in enumerate(boxes):
        for second in boxes[index + 1 :]:
            width = min(first["right"], second["right"]) - max(first["left"], second["left"])
            height = min(first["bottom"], second["bottom"]) - max(first["top"], second["top"])
            if width > 1 and height > 1:
                overlaps.append(f"{first['text']!r} overlaps {second['text']!r}")
    assert overlaps == []


@pytest.mark.parametrize("name", PAGES)
def test_text_is_legible_and_not_clipped(page: Page, report: ReportHome, name: str) -> None:
    _open(page, report, name)
    boxes = page.evaluate(_LAYOUT_SCRIPT, _TEXT_SELECTOR)

    too_small = [box["text"] for box in boxes if box["fontSize"] < 11]
    assert too_small == []
    clipped = [
        box["text"]
        for box in boxes
        if box["clientWidth"] > 0 and box["scrollWidth"] > box["clientWidth"] + 1
    ]
    assert clipped == []


@pytest.mark.parametrize("name", PAGES)
def test_cards_in_a_row_share_their_top_edge(page: Page, report: ReportHome, name: str) -> None:
    """Grid children must line up: stacked-card margins must not leak into grids."""
    _open(page, report, name)
    rows = page.evaluate(
        """() => Array.from(document.querySelectorAll(".kpi-grid, .grid-2")).map((grid) =>
            Array.from(grid.children).map((child) => {
                const rect = child.getBoundingClientRect();
                return { top: rect.top, bottom: rect.bottom, left: rect.left };
            })
        )"""
    )
    misaligned: list[str] = []
    for cards in rows:
        for index, first in enumerate(cards):
            for second in cards[index + 1 :]:
                same_row = (
                    second["top"] < first["bottom"] - 1 and first["top"] < second["bottom"] - 1
                )
                if same_row and abs(first["top"] - second["top"]) > 1:
                    misaligned.append(f"{first['top']:.0f} vs {second['top']:.0f}")
    assert misaligned == []


@pytest.mark.parametrize(("name", "series"), LEGEND_SERIES.items())
def test_multi_series_charts_show_a_legend(
    page: Page, report: ReportHome, name: str, series: int
) -> None:
    _open(page, report, name)

    charts = page.evaluate(
        """() => Array.from(document.querySelectorAll(".chart")).map((element) => {
            const chart = window.echarts.getInstanceByDom(element);
            if (!chart) { return null; }
            const option = chart.getOption();
            const legend = (option.legend || [])[0] || {};
            return {
                visible: legend.show !== false,
                entries: (legend.data || []).length,
                series: (option.series || []).map((item) => item.name).filter(Boolean),
                canvas: !!element.querySelector("canvas")
            };
        })"""
    )
    assert charts
    assert all(chart is not None for chart in charts)
    for chart in charts:
        assert chart["canvas"] is True
        if chart["visible"] is True:
            entries = max(chart["entries"], len(chart["series"]))
            assert entries >= series


@pytest.mark.parametrize("name", PAGES)
def test_pages_do_not_scroll_horizontally(page: Page, report: ReportHome, name: str) -> None:
    _open(page, report, name)
    measurements = page.evaluate(
        """() => ({
            scrollWidth: document.documentElement.scrollWidth,
            clientWidth: document.documentElement.clientWidth,
            viewport: window.innerWidth
        })"""
    )
    assert measurements["scrollWidth"] <= measurements["clientWidth"] + 1
    assert measurements["clientWidth"] <= measurements["viewport"]
