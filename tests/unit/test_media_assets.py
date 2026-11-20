"""Guards for the committed report media assets (T13)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageStat

MEDIA = Path(__file__).resolve().parents[2] / "docs" / "media"
SCREENSHOTS = tuple(
    f"{page}-{theme}.png"
    for theme in ("light", "dark")
    for page in ("index", "tax", "prices", "macro")
)
GIF_MAX_BYTES = 2_621_440
MIN_PIXEL_STDDEV = 6.0


@pytest.mark.parametrize("name", SCREENSHOTS)
def test_screenshot_is_a_non_blank_1440x900_image(name: str) -> None:
    path = MEDIA / name
    assert path.is_file(), f"missing screenshot {name}; run scripts/capture_media.py"
    with Image.open(path) as image:
        assert image.size == (1440, 900)
        assert ImageStat.Stat(image.convert("L")).stddev[0] >= MIN_PIXEL_STDDEV


def test_demo_gif_respects_the_budget_and_walks_the_pages() -> None:
    path = MEDIA / "demo.gif"
    assert path.is_file(), "missing demo.gif; run scripts/capture_media.py"
    assert path.stat().st_size <= GIF_MAX_BYTES
    with Image.open(path) as image:
        assert image.size[0] == 800
        frames = getattr(image, "n_frames", 1)
        assert frames >= 10
        durations = []
        for index in range(frames):
            image.seek(index)
            durations.append(image.info.get("duration", 0))
            assert ImageStat.Stat(image.convert("L")).stddev[0] >= MIN_PIXEL_STDDEV
        assert all(duration > 0 for duration in durations)
