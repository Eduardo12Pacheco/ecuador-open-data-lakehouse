"""Session fixtures for the browser end-to-end suite (S16, T13).

One sample lakehouse is built through the real CLI and served on an ephemeral
loopback port for the whole session; Chromium is launched once. Tests never
reach the network beyond that loopback origin, and failure screenshots land in
the git-ignored ``test-results/e2e`` directory so CI can upload them.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, ConsoleMessage, Page, sync_playwright
from typer.testing import CliRunner

from ecuador_lakehouse.adapters.report.server import create_server, server_url
from ecuador_lakehouse.cli.app import app

runner = CliRunner()
SCREENSHOT_DIR = Path(__file__).resolve().parents[2] / "test-results" / "e2e"
VIEWPORT = {"width": 1440, "height": 900}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]) -> Iterator[None]:
    """Attach each test report to the item so the page fixture can screenshot failures."""
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@dataclass(frozen=True, slots=True)
class ReportHome:
    """A fully built sample lakehouse and the served URL of its report site."""

    home: Path
    site: Path
    url: str


@pytest.fixture(scope="session")
def built_home(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the real ``lakehouse build`` once for the browser suite."""
    home = tmp_path_factory.mktemp("e2e-home")
    result = runner.invoke(app, ["build"], env={"LAKEHOUSE_HOME": str(home)})
    if result.exit_code != 0:
        pytest.fail(f"lakehouse build failed for the e2e home: {result.output}", pytrace=False)
    assert (home / "site" / "index.html").is_file()
    return home


@pytest.fixture(scope="session")
def report(built_home: Path) -> Iterator[ReportHome]:
    """Serve the generated site on an ephemeral loopback port in a thread."""
    site = built_home / "site"
    server = create_server(site, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, name="e2e-report-server", daemon=True)
    thread.start()
    try:
        yield ReportHome(home=built_home, site=site, url=server_url(server))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    """Launch one headless Chromium for the whole session."""
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch()
        try:
            yield launched
        finally:
            launched.close()


@pytest.fixture
def context(browser: Browser) -> Iterator[BrowserContext]:
    """A fresh 1440x900 browser context per test."""
    created = browser.new_context(viewport=VIEWPORT)
    try:
        yield created
    finally:
        created.close()


@pytest.fixture
def console_errors(context: BrowserContext) -> list[str]:
    """Console errors and uncaught page errors recorded for the current page."""
    errors: list[str] = []

    def record(message: ConsoleMessage) -> None:
        if message.type == "error":
            errors.append(f"console: {message.text}")

    def record_page_error(error: BaseException) -> None:
        errors.append(f"pageerror: {error}")

    context.on("console", record)
    context.on("pageerror", record_page_error)
    return errors


@pytest.fixture
def page(context: BrowserContext, request: pytest.FixtureRequest) -> Iterator[Page]:
    """A page that saves a full-page screenshot when its test fails."""
    created = context.new_page()
    try:
        yield created
    finally:
        report = getattr(request.node, "rep_call", None)
        if report is not None and report.failed:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            name = request.node.name.replace("/", "_").replace("::", "_")
            created.screenshot(path=str(SCREENSHOT_DIR / f"{name}.png"), full_page=True)
        created.close()
