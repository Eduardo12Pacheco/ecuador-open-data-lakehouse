# ADR 0001 — Python 3.12, DuckDB and dbt as the analytics stack

## Status

Accepted (2026-11-19). Refined by ADR 0003 (EL in Python, T in dbt) and ADR 0006
(custom DAG runner instead of Dagster).

## Context

The lakehouse must install as a single Python package (install level L1), run
fully offline from a bundled sample, need no account or server, and still look
like a real analytics-engineering platform rather than a notebook. The full
data set is roughly seven million rows across SRI tax collection, INEC CPI and
BCE national accounts. The machine is a developer laptop (Linux, but Windows and
macOS must work too), and the same code participates in a three-OS CI matrix.

The transformation layer is a first-class deliverable: staging, intermediate and
mart models, contracts, data tests, unit tests, lineage documentation and
incremental loads. Writing that layer as hand-rolled Python would demonstrate
SQL skills poorly and would turn every modelling change into application code.

## Decision

- Python 3.12, `uv` for resolution and locking, `hatchling` as the build backend,
  `src/` layout, distribution `ecuador-open-data-lakehouse`, import package
  `ecuador_lakehouse`, console script `lakehouse`.
- DuckDB (2.x) as the single-file warehouse at `$LAKEHOUSE_HOME/warehouse.duckdb`,
  with schemas `raw`, `staging`, `intermediate`, `marts` and `meta`.
- dbt-core 1.12 and dbt-duckdb 1.11, invoked in-process through
  `dbt.cli.main.dbtRunner` so the installed wheel owns the project, profiles and
  target paths. The dbt project is copied from package resources into
  `$LAKEHOUSE_HOME/dbt/project` before a run.
- Python owns extraction and structural decoding; dbt owns typing, cleaning,
  keys, star-schema models and tests (ADR 0003).
- The warehouse connection is closed before dbt starts, because DuckDB allows a
  single writer per database file.

## Consequences

- One process, no services to start: `lakehouse build` is enough.
- DuckDB gives columnar analytical performance and SQL that would be painful in
  SQLite, while the wheel stays a normal Python package.
- The single-writer rule constrains concurrency. It is handled by opening the
  warehouse only in the EL phase and closing it before dbt, and by keeping dbt
  threads at four.
- A dbt environment is about 350 MB installed, accepted for L1 because the task
  requires a genuine transformation framework.
- Absolute paths are required for dbt's `--project-dir`, `--profiles-dir`,
  `--target-path` and `--log-path`; artifacts and logs stay under
  `$LAKEHOUSE_HOME`, never in the repository.
- The published artifact can embed DuckDB and Parquet without any external
  service, and `content_sha256` values stay reproducible (ADR 0007).

## Alternatives considered

- **PostgreSQL**: needs a service and credentials, contradicting L1 and the
  zero-server constraint.
- **Apache Spark**: JVM, large downloads, cluster-oriented semantics, and far
  too heavy for a laptop demo.
- **pandas/Polars notebooks**: quick to write, but the transformation layer
  would stop being SQL, would not produce a dbt manifest, and would not support
  dbt data/unit tests or lineage docs.
- **SQLite**: embedded and simple, but weak analytical SQL, no columnar scans,
  and no idiomatic dbt adapter with contract support.
- **Cloud warehouse (BigQuery/Snowflake)**: accounts, keys, cost and network
  dependencies; excluded by the project standards.
