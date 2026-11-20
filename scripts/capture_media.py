"""Capture the report screenshots and the animated demo GIF (T13).

The script builds a disposable sample lakehouse (unless ``--home`` points at an
existing one), serves the generated site on an ephemeral loopback port and uses
Playwright Chromium to capture:

* ``docs/media/<page>-<theme>.png`` for overview, tax, prices and macro in both
  themes at 1440x900;
* ``docs/media/demo.gif``, about twelve frames that walk through the pages,
  800 px wide and under the size budget.

Every image is validated for non-blank pixels before it is kept. Run it with:

    uv run python scripts/capture_media.py
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageStat
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from ecuador_lakehouse.adapters.report.server import create_server, server_url

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "media"

SCREENSHOT_PAGES = ("index", "tax", "prices", "macro")
THEMES = ("light", "dark")
SCREENSHOT_SIZE = {"width": 1440, "height": 900}
GIF_WIDTH = 800
GIF_MAX_BYTES = 2_621_440
MIN_PIXEL_STDDEV = 6.0
READY = 'html[data-ready="true"]'
CHART_SETTLE_MS = 750

# A walk through the site: page, vertical scroll fraction and theme.
GIF_FRAMES: tuple[tuple[str, float, str], ...] = (
    ("index", 0.0, "light"),
    ("index", 0.55, "light"),
    ("index", 0.0, "dark"),
    ("tax", 0.0, "light"),
    ("tax", 0.45, "light"),
    ("tax", 0.0, "dark"),
    ("prices", 0.0, "light"),
    ("prices", 0.45, "light"),
    ("macro", 0.0, "light"),
    ("macro", 0.45, "light"),
    ("quality", 0.0, "light"),
    ("sources", 0.0, "light"),
)


@dataclass(frozen=True, slots=True)
class CaptureTarget:
    """A served report site plus the directory that receives the media files."""

    url: str
    output_dir: Path


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture report screenshots and the demo GIF.")
    parser.add_argument(
        "--home",
        type=Path,
        default=None,
        help="existing LAKEHOUSE_HOME with a built site (default: build a temporary one)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output directory (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    return parser.parse_args(argv)


def _ensure_built(home: Path) -> None:
    """Build the disposable sample lakehouse when no site exists yet."""
    if (home / "site" / "index.html").is_file():
        return
    sys.stdout.write("building a disposable sample lakehouse for the captures\n")
    env = {**os.environ, "LAKEHOUSE_HOME": str(home)}
    subprocess.run([sys.executable, "-m", "ecuador_lakehouse", "build"], check=True, env=env)


@contextmanager
def _served_site(home: Path) -> Iterator[str]:
    _ensure_built(home)
    server = create_server(home / "site", host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, name="capture-server", daemon=True)
    thread.start()
    try:
        yield server_url(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


@contextmanager
def _context(browser: Browser, *, viewport: dict[str, int], theme: str) -> Iterator[BrowserContext]:
    context = browser.new_context(viewport=viewport, color_scheme=theme, device_scale_factor=1)
    context.add_init_script("try { localStorage.clear(); } catch (error) {}")
    try:
        yield context
    finally:
        context.close()


def _open(page: Page, url: str, name: str) -> None:
    response = page.goto(f"{url}/{name}.html", wait_until="load")
    if response is None or not response.ok:
        raise RuntimeError(f"could not load {name}.html from the report server")
    page.wait_for_selector(READY)
    page.wait_for_timeout(CHART_SETTLE_MS)


def _assert_not_blank(image: Image.Image, label: str) -> None:
    grayscale = image.convert("L")
    stddev = ImageStat.Stat(grayscale).stddev[0]
    if stddev < MIN_PIXEL_STDDEV:
        raise RuntimeError(f"{label} looks blank (pixel stddev {stddev:.2f})")


def _capture_screenshots(browser: Browser, target: CaptureTarget) -> list[Path]:
    written: list[Path] = []
    for theme in THEMES:
        with _context(browser, viewport=SCREENSHOT_SIZE, theme=theme) as context:
            page = context.new_page()
            for name in SCREENSHOT_PAGES:
                _open(page, target.url, name)
                path = target.output_dir / f"{name}-{theme}.png"
                page.screenshot(path=str(path), full_page=False)
                with Image.open(path) as image:
                    size = image.size
                    _assert_not_blank(image, path.name)
                if size != (SCREENSHOT_SIZE["width"], SCREENSHOT_SIZE["height"]):
                    raise RuntimeError(f"{path.name} is {size}, expected 1440x900")
                written.append(path)
                sys.stdout.write(f"wrote {path.relative_to(REPO_ROOT)} ({size[0]}x{size[1]})\n")
    return written


def _gif_frame(page: Page, url: str, name: str, scroll: float) -> Image.Image:
    _open(page, url, name)
    page.evaluate(
        """(fraction) => {
            const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
            window.scrollTo(0, Math.round(max * fraction));
        }""",
        scroll,
    )
    page.wait_for_timeout(250)
    payload = page.screenshot(full_page=False)
    image = Image.open(io.BytesIO(payload)).convert("RGB")
    height = round(image.height * GIF_WIDTH / image.width)
    return image.resize((GIF_WIDTH, height), Image.Resampling.LANCZOS)


def _capture_gif(browser: Browser, target: CaptureTarget) -> Path:
    frames: list[Image.Image] = []
    viewport = {"width": 1000, "height": 700}
    for theme in ("light", "dark"):
        with _context(browser, viewport=viewport, theme=theme) as context:
            page = context.new_page()
            for name, scroll, frame_theme in GIF_FRAMES:
                if frame_theme != theme:
                    continue
                frames.append(_gif_frame(page, target.url, name, scroll))

    if len(frames) != len(GIF_FRAMES):
        raise RuntimeError(f"captured {len(frames)} GIF frames, expected {len(GIF_FRAMES)}")
    for index, frame in enumerate(frames):
        _assert_not_blank(frame, f"GIF frame {index + 1}")

    path = target.output_dir / "demo.gif"
    paletted = [frame.convert("P", palette=Image.Palette.ADAPTIVE, colors=96) for frame in frames]
    paletted[0].save(
        path,
        save_all=True,
        append_images=paletted[1:],
        duration=900,
        loop=0,
        optimize=True,
        disposal=2,
    )
    size = path.stat().st_size
    if size > GIF_MAX_BYTES:
        raise RuntimeError(f"demo.gif is {size} bytes, above the {GIF_MAX_BYTES} byte budget")
    sys.stdout.write(f"wrote {path.relative_to(REPO_ROOT)} ({size} bytes, {len(frames)} frames)\n")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir: Path = args.out
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="lakehouse-media-") as scratch:
        home = args.home if args.home is not None else Path(scratch)
        with _served_site(home) as url:
            target = CaptureTarget(url=url, output_dir=output_dir)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    screenshots = _capture_screenshots(browser, target)
                    gif = _capture_gif(browser, target)
                finally:
                    browser.close()

    relative = output_dir.relative_to(REPO_ROOT)
    sys.stdout.write(f"captured {len(screenshots)} screenshots and {gif.name} in {relative}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
