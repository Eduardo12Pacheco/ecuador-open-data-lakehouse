"""The report site must also work when opened directly through ``file://`` (S16)."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


READY = 'html[data-ready="true"]'


def test_overview_renders_from_the_file_scheme(
    page: Page, built_home: Path, console_errors: list[str]
) -> None:
    index = built_home / "site" / "index.html"
    page.goto(index.as_uri(), wait_until="load")
    page.wait_for_selector(READY)
    page.wait_for_timeout(250)

    assert page.evaluate("location.protocol") == "file:"
    assert page.evaluate("document.documentElement.dataset.theme") in {"light", "dark"}
    assert page.locator("#chart-overview-monthly canvas").count() == 1
    total = page.locator('[data-kpi="latest_full_year_total"]').first.inner_text()
    assert total.startswith("$")
    assert page.locator("#error-banner").is_hidden()
    assert console_errors == []


def test_theme_toggle_works_from_the_file_scheme(page: Page, built_home: Path) -> None:
    index = built_home / "site" / "index.html"
    page.goto(index.as_uri(), wait_until="load")
    page.wait_for_selector(READY)
    before = page.evaluate("document.documentElement.dataset.theme")

    page.click("#theme-toggle")
    after = page.evaluate("document.documentElement.dataset.theme")
    assert after != before
    assert page.locator("#chart-overview-monthly canvas").count() == 1
