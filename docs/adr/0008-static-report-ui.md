# ADR 0008 - Static multi-page report UI

## Status

Accepted (2026-11-20, task T12).

## Context

The lakehouse must show its results to someone who does not have a notebook
open: tax collection, prices, macro data, the quality gate and the source
provenance. The UI has to run offline on Linux, Windows and macOS, ship inside
the same wheel as the CLI, work from `file://` as well as from a local server,
support light and dark themes, and never fetch assets from a CDN (S2, S16).

Candidates considered:

- **Streamlit.** Fast to prototype, but it adds a server runtime, a large
  dependency tree and a look that is hard to make product-quality. It also
  conflicts with the L1 "install a CLI, no services" level.
- **Evidence.dev.** Excellent for BI reports, but it needs Node/npm and a build
  toolchain, so it cannot ship through `uv tool install`.
- **A React/Vite SPA.** Flexible, but adds a Node build step and a client-side
  bundle pipeline for a read-only report; overkill for six pages.
- **Jinja2 templates + vendored ECharts.** Plain HTML files, a stdlib HTTP
  server, no build step and no runtime dependency beyond Jinja2, which the
  project already uses. Charts are rendered client-side from JSON embedded in
  each page, so the same files work from `file://`.

## Decision

1. **Generate static HTML with Jinja2.** `application.use_cases.build_report`
   orchestrates a read-only `ReportReader` port and a `ReportRenderer` port.
   `adapters.report.renderer.JinjaReportRenderer` writes `index.html`,
   `tax.html`, `prices.html`, `macro.html`, `quality.html`, `sources.html` and
   an explicit `empty.html`, and copies the assets into `site/assets/`.
2. **Embed data, not requests.** The reader aggregates every page dataset in
   one DuckDB read-only connection and the renderer serializes each page's data
   into a `<script type="application/json" id="data-<page>">` block. No page
   calls `fetch`, so `file://` and `http://127.0.0.1` behave identically.
3. **Vendor ECharts 6.1.0.** `scripts/vendor_echarts.py` downloads the pinned
   bundle, verifies size and SHA-256 (`b66b25ae…fd0`, 1,121,883 bytes) and
   writes it to the package assets, together with the Apache-2.0 license and
   notice. No CDN is contacted at runtime and a test pins the checksum.
4. **Design tokens and contrast.** `tokens.css` defines light and dark custom
   properties; `tests/unit/test_contrast.py` computes WCAG ratios from the CSS
   and enforces 4.5:1 for text and 3:1 for chart colors in both themes.
5. **Accessible by construction.** Skip link, landmark header/nav/main/footer,
   visible focus rings, keyboard-operable selects and sortable table headers,
   `aria-sort`, `<noscript>`, explicit empty and error states, and
   `prefers-reduced-motion` support.
6. **Loopback-only server.** `lakehouse serve` binds `127.0.0.1` on port 15080
   by default (configurable with `--host/--port` and `LAKEHOUSE_SERVE_*`), only
   accepts loopback addresses and serves exclusively from the generated site.
   If the site is missing it is generated first; if the warehouse is missing
   the command exits 2 with an actionable message.
7. **Report data stays out of the artifact contract.** The UI reads marts, but
   the report itself is not a published data product; the artifact contract and
   determinism guarantees cover only the DuckDB/Parquet artifact (ADR 0007).

## Consequences

- The report is a set of files that can be attached to a release, opened from a
  USB drive or served by any static file host without changing a line.
- The UI is testable without a browser: JSON blocks, local-link checks, contrast
  math and the stdlib server are covered by pytest; Playwright e2e arrives in
  T13.
- Adding a page means adding a template, one entry in the renderer and one data
  query; the shell, theme and navigation are shared.
- ECharts adds ~1.1 MB to the wheel, an accepted cost for a genuinely offline,
  interactive report.
- The server is intentionally not a production server: single-user, loopback
  only, no authentication, no TLS. This matches the local-first constraint.

## Alternatives

- **Streamlit** rejected: heavy runtime, server requirement, limited styling.
- **Evidence.dev** rejected: Node toolchain, generated site needs a build.
- **React SPA** rejected: extra toolchain for a read-only report.
- **Matplotlib/PNG charts** rejected: static images cannot support year and city
  filters or theme switching without regenerating files.
