# ADR 0006 — A custom DAG runner instead of Dagster/Airflow

## Status

Accepted (2026-11-20).

## Context

The project needs a reproducible pipeline that runs `acquire -> load_raw ->
transform -> quality -> docs -> report` from one CLI command, supports partial
re-runs, retries idempotent acquisition, stops before downstream steps when a
step fails, and records what happened in `meta.runs` (S13, D6). The pipeline has
six steps, one process, one local DuckDB file and no scheduling requirements.

The obvious alternatives are:

1. **Dagster** — asset/materialization model, retries, run history and a web
   UI. Version 1.13.31 pulls in grpcio, SQLAlchemy, Alembic and a daemon, and
   its normal usage assumes a persistent instance and a web service.
2. **Airflow** — mature scheduler, but a scheduler, metadata database, webserver
   and executor are required even for a single local DAG.
3. **A tiny pure-Python DAG** — a validated graph plus a loop that executes
   callables, with the run ledger stored in the same DuckDB file.

The standards require a local-first L1 install (`uv tool install`, no Docker, no
server) and the plan explicitly makes the orchestrator a non-goal for external
services (Context: "no orchestrator service — see ADR 0006").

## Decision

- **Keep the orchestrator custom and small.** `domain.dag.Dag` validates
  duplicate steps, unknown dependencies and cycles at construction time and
  returns a deterministic topological order (ties alphabetical).
  `application.pipeline.PipelineRunner` executes registered callables, supports
  `--select` (step plus transitive upstream), `--only` (one step) and
  `--from-step` (step plus downstream), stops at the first failure and records
  one `meta.runs` row per invocation with per-step status, duration, attempts,
  detail and numeric metrics as compact JSON.
- **Retries are opt-in and idempotency is asserted.** Only steps declared
  idempotent may receive a `RetryPolicy`; the runner rejects a policy for any
  other step at construction time. Today only `acquire` is retried, because
  re-fetching a verified file is safe, while a partially applied load or dbt
  run is not blindly repeated.
- **Steps are plain application callables wired by the composition root.** The
  runner knows nothing about DuckDB, dbt or HTTP. `container.py` selects the
  fetch strategy by mode, assembles the six steps and passes the warehouse as
  the run-ledger repository. A Dagster wrapper would only need to call the same
  callables.
- **The run ledger lives in `meta.runs`.** One row per run (start/finish, status,
  mode, steps JSON) is written at the end of the run, including failed runs, so
  the state of the last build is inspectable with plain SQL and can be shown by
  the report UI without external infrastructure.
- **dbt gets exclusive access to the warehouse.** The transform, quality and
  docs steps close the application connection before invoking dbt and reopen it
  afterwards (D18). The report step then reads the ledger through the reopened
  connection.

## Consequences

- Positive: zero extra services, no daemon, no metadata database, install stays
  ~350 MB dominated by dbt; the pipeline runs offline and on Windows.
- Positive: ordering, selection and retry behaviour are unit-tested against the
  real `Dag`, and `meta.runs` is asserted by integration tests.
- Positive: replacing the runner with Dagster later means implementing the same
  six callables as assets; no domain or adapter logic is trapped in the runner.
- Negative: no UI, scheduler, alerting or distributed execution. The project is
  a local batch lakehouse by design; scheduling (cron, GitHub Actions) is out of
  scope.
- Negative: the runner is our code to maintain. Its surface is intentionally
  small (one module plus the pure DAG) and covered by unit tests and property
  tests for graph ordering/cycles.
