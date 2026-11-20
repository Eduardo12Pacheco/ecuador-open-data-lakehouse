"""Vendor the pinned ECharts distribution into the report assets (S16).

ECharts is Apache-2.0 and is bundled locally so the report works offline and
from ``file://``. The download is verified against the pinned size and SHA-256;
a mismatch fails loudly instead of silently rendering a different library.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import urllib.request
from pathlib import Path

ECHARTS_VERSION = "6.1.0"
ECHARTS_URL = f"https://cdn.jsdelivr.net/npm/echarts@{ECHARTS_VERSION}/dist/echarts.min.js"
ECHARTS_SHA256 = "b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0"
ECHARTS_BYTES = 1_121_883

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "ecuador_lakehouse"
    / "adapters"
    / "report"
    / "assets"
    / "echarts.min.js"
)


def _digest(path: Path) -> tuple[str, int]:
    payload = path.read_bytes()
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _download(destination: Path) -> None:
    request = urllib.request.Request(
        ECHARTS_URL,
        headers={"User-Agent": "ecuador-open-data-lakehouse/vendor-echarts"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - pinned HTTPS URL
        payload = response.read(ECHARTS_BYTES + 1)
    if len(payload) != ECHARTS_BYTES:
        raise SystemExit(f"unexpected ECharts size: {len(payload)} bytes")
    destination.write_bytes(payload)


def main() -> int:
    """Download, verify and install the vendored ECharts bundle."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    output: Path = arguments.output
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="echarts-") as scratch:
        candidate = Path(scratch) / "echarts.min.js"
        _download(candidate)
        digest, size = _digest(candidate)
        if digest != ECHARTS_SHA256 or size != ECHARTS_BYTES:
            raise SystemExit(
                f"ECharts checksum mismatch: got {size} bytes {digest}, "
                f"expected {ECHARTS_BYTES} bytes {ECHARTS_SHA256}"
            )
        output.write_bytes(candidate.read_bytes())
    sys.stdout.write(
        f"vendored ECharts {ECHARTS_VERSION}: {ECHARTS_BYTES} bytes sha256 {ECHARTS_SHA256}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
