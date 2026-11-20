# ADR 0003 — Extraction/loading in Python, transformation in dbt

## Status

Accepted (2026-11-20).

## Context

The three upstream sources are structurally messy in different ways. SRI ships
one 83–109 MB `|`-delimited file per year, UTF-8 with a BOM until 2022 and
cp1252 from 2023, with comma decimals and no stable column set (`CANTON` is
missing in older files). BCE ships a 6 MB `;`-delimited cp1252 file with comma
thousands separators, 176 empty values and negative amounts. INEC ships a ZIP
nested three levels deep whose CSVs are wide-pivoted across 120 month columns,
mix `1,000000` and `0.224503124`, and carry title and footer rows.

The alternative of teaching dbt to read each raw format directly would push
encoding detection, nested-archive traversal and header discovery into SQL
models, where they are hard to test in isolation and impossible to reuse for
the published sample. Conversely, doing all cleaning in Python would duplicate
the typing, key generation and data tests that dbt already provides and would
make the transformation layer inaccessible to analysts.

## Decision

- Python adapters own **structural extraction only (EL)**: decode with the D13
  policy, validate the upstream header, traverse nested archives, find the
  header row, unpivot wide month columns, and write canonical UTF-8 CSV with
  LF endings. Every source value is preserved as raw text in that CSV.
- dbt owns **all typing, normalization, key generation and modelling (T)**:
  casting, decimal separators, month parsing, `normalize_key` parity,
  surrogate keys, dimensions, facts, marts, data tests and unit tests.
- The warehouse bulk-loads each canonical CSV through DuckDB `read_csv` with
  `all_varchar=true`; parsers never import DuckDB, dbt or pandas. This keeps
  the install light and avoids loading 100 MB files into Python objects.
- Parsers implement the `SourceParser` port (`source_id`, `parse(path,
  partition, output_dir=None) -> ParsedPartition`) and raise
  `SourceSchemaError` (exit code 4) for missing or unknown columns, an
  unreadable archive or an undecodable file. Unknown headers are rejected
  instead of being silently ignored, so upstream drift fails loudly.
- The canonical CSV contract is fixed per source and documented in the parser
  modules; it is the only interface between EL and T.

## Consequences

- Every format quirk has a small fixture-based unit test without a warehouse
  or dbt, and the same parser feeds both the bundled sample and `full` mode.
- dbt remains the single transformation engine: models, tests, lineage and
  documentation describe the whole business logic.
- The canonical CSV adds one temporary file per partition (small compared with
  the upstream bytes) but makes loading simple, inspectable and database
  agnostic.
- Raw text stays raw until dbt, so a value such as `-40,290` or an empty CNT
  cell is preserved exactly and failures happen in a tested SQL layer.
- Structural drift that changes only values (for example a new province) is not
  a parser error; it is caught later by relationship or accepted-values tests.
  Drift that changes columns fails early with exit code 4.

## Alternatives considered

- **Read raw files directly from dbt**: encoding sniffing and nested ZIPs in
  SQL are brittle, and dbt-duckdb would still need Python `read_csv` semantics.
- **Full cleaning in Python (pandas/polars)**: contradicts D5, adds a heavy
  dependency, duplicates dbt tests and weakens the "dbt is the transformation
  engine" story.
- **One parser per file format with Python `csv.DictReader` only**: does not
  handle the INEC nested ZIPs or the SRI header drift, so the adapters still
  need explicit header validation and archive handling.
