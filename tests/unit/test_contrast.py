"""WCAG contrast checks for both report themes (S16).

Every text token must reach 4.5:1 against every surface it can appear on, and
every chart palette token must reach 3:1 (graphical objects). The ratios are
computed from ``tokens.css`` so a palette change cannot silently regress.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TOKENS_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "ecuador_lakehouse"
    / "adapters"
    / "report"
    / "assets"
    / "tokens.css"
)

SURFACES = ("bg", "surface", "surface-alt")
CHART_TOKENS = tuple(f"chart-{index}" for index in range(1, 9))
REQUIRED_TOKENS = (
    *SURFACES,
    "text",
    "text-muted",
    "border",
    "accent",
    "accent-contrast",
    "focus",
    "success",
    "warning",
    "danger",
    *CHART_TOKENS,
)

_HEX = re.compile(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;")


def _parse_theme(css: str, selector: str) -> dict[str, str]:
    start = css.index(selector)
    end = css.find("}", start)
    assert end != -1, f"unterminated {selector} block"
    return {name: value.lower() for name, value in _HEX.findall(css[start:end])}


def _channel(value: float) -> float:
    if value <= 0.03928:
        return value / 12.92
    return ((value + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    red, green, blue = (int(color[index : index + 2], 16) / 255 for index in (1, 3, 5))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast(foreground: str, background: str) -> float:
    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.fixture(scope="module")
def themes() -> dict[str, dict[str, str]]:
    css = TOKENS_PATH.read_text(encoding="utf-8")
    return {
        "light": _parse_theme(css, ":root"),
        "dark": _parse_theme(css, '[data-theme="dark"]'),
    }


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_theme_defines_every_required_token(themes: dict[str, dict[str, str]], theme: str) -> None:
    tokens = themes[theme]
    missing = [name for name in REQUIRED_TOKENS if name not in tokens]
    assert not missing, f"{theme} theme is missing tokens: {', '.join(missing)}"


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("surface", SURFACES)
def test_text_and_muted_text_are_readable_on_every_surface(
    themes: dict[str, dict[str, str]], theme: str, surface: str
) -> None:
    tokens = themes[theme]
    background = tokens[surface]
    for name in ("text", "text-muted", "accent"):
        ratio = contrast(tokens[name], background)
        assert ratio >= 4.5, f"{theme}: {name} on {surface} is only {ratio:.2f}:1"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_accent_foreground_and_semantic_colors_pass(
    themes: dict[str, dict[str, str]], theme: str
) -> None:
    tokens = themes[theme]
    assert contrast(tokens["accent-contrast"], tokens["accent"]) >= 4.5
    for name in ("success", "warning", "danger"):
        for surface in ("surface", "bg"):
            ratio = contrast(tokens[name], tokens[surface])
            assert ratio >= 4.5, f"{theme}: {name} on {surface} is only {ratio:.2f}:1"


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("token", CHART_TOKENS)
@pytest.mark.parametrize("surface", ["surface", "bg"])
def test_chart_palette_has_graphical_contrast(
    themes: dict[str, dict[str, str]], theme: str, token: str, surface: str
) -> None:
    ratio = contrast(themes[theme][token], themes[theme][surface])
    assert ratio >= 3.0, f"{theme}: {token} on {surface} is only {ratio:.2f}:1"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_focus_ring_is_visible(themes: dict[str, dict[str, str]], theme: str) -> None:
    ratio = contrast(themes[theme]["focus"], themes[theme]["bg"])
    assert ratio >= 3.0, f"{theme}: focus ring is only {ratio:.2f}:1 on the page background"
