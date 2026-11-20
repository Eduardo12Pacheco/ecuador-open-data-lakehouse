# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-11-20

### Fixed

- Report UI: cards in the KPI and two-column grids are top-aligned again (the
  stacked-card margin no longer leaks into grid children); an e2e test pins it.
- Report UI: the division-inflation chart no longer collapses its plot area under
  long Spanish labels, every province is labelled in the province chart, and the
  ratio chart axis title is no longer clipped.
- Release workflow: the tag must match the package version, only the wheel, sdist
  and sample-artifact zip are attached (never stray CI artifacts), and
  `SHA256SUMS` lists bare file names so `sha256sum -c` works; re-running the
  release job on an existing release uploads the assets instead of failing.
- CI security job: grants the read permission the secret scan needs on pull
  requests (the release caller grants it too, and a contract test pins that a
  called workflow never asks for more than its caller) and states honestly that
  it scans the pushed commits.

### Changed

- The release-wheel install URL in both READMEs is pinned to the tag, so it keeps
  working after the next release.
- READMEs show the light and dark theme screenshots; media regenerated.
- `examples/consume_artifact.py` reports how many months of the latest year are
  loaded instead of presenting a partial year as complete.
- Package metadata gains project URLs; `CONTRIBUTING.md` documents the release
  procedure; version assertions in tests derive from `pyproject.toml`.

## [0.1.0] - 2026-11-20

### Added

- Local-first `lakehouse` CLI (`build`, `test`, `serve`, `fetch`, `sample`,
  `docs`, `publish`, `verify`, `doctor`, `contract check`) installable with
  `uv tool install`, with typed settings, structlog output and documented exit
  codes.
- Pinned, checksummed acquisition for SRI tax collection, INEC consumer prices
  and BCE national accounts, with license evidence, a host allow-list, resumable
  downloads and a fully offline bundled sample.
- Resilient parsers for UTF-8 BOM and cp1252 CSVs, comma decimals, semicolon
  delimiters, nested zips and wide Spanish-month CPI tables.
- DuckDB raw layer with an idempotent batch ledger and one-transaction partition
  loads, plus a deterministic province-grain sample builder.
- dbt project with staging, intermediate and marts layers: 7 dimensions, 3 facts,
  4 analytic marts, an SCD2 tax-line dimension and partition-level incremental
  fact loads.
- Data-quality suite with dbt data tests, unit tests, singular reconciliation
  tests, control totals, Hypothesis property tests and a quality gate.
- Custom DAG pipeline runner with step selection, per-step retries, run ledger
  and structured logs.
- Published data product with DuckDB, ZSTD Parquet, manifest, `SHA256SUMS`,
  semver contract enforcement, `verify` tamper detection and a consumer example.
- Static multi-page report served on loopback with vendored ECharts, light/dark
  themes, accessible contrast, keyboard navigation and empty/error states.
- CI matrix on Linux, Windows and macOS, Playwright e2e job, installer smoke
  matrix, security jobs and a tag-driven release workflow.
- Documentation set: architecture, data, artifact and contract guides,
  configuration reference, generated lineage, ADRs, README and Spanish mirror.

[Unreleased]: https://github.com/Eduardo12Pacheco/ecuador-open-data-lakehouse/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Eduardo12Pacheco/ecuador-open-data-lakehouse/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/Eduardo12Pacheco/ecuador-open-data-lakehouse/releases/tag/v0.1.0
