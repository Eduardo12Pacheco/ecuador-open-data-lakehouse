# ADR 0002 — Hexagonal architecture enforced by import-linter and AST tests

## Status

Accepted (2026-11-19).

## Context

The project mixes several concerns that are easy to entangle: pure business
rules (canonical text keys, batch identifiers, the pipeline DAG), use cases
(acquire, load, transform, publish), and I/O adapters (HTTP, DuckDB, dbt, the
report renderer, the CLI). The portfolio standard requires hexagonal
architecture with the dependency direction enforced by a test, not by
convention or code review alone.

The domain must stay cheap to test: no network, no database, no dbt, no
filesystem. The application layer may orchestrate I/O through ports and may use
the standard library for files, but must not reach into adapters or third-party
I/O libraries. Adapters must be mutually independent so a parser cannot import
the warehouse and a warehouse cannot import the report renderer.

## Decision

- Packages: `domain/`, `application/`, `adapters/`, `cli/`, plus the composition
  root `container.py`, `config.py` and `logging_setup.py`.
- Dependency direction: `cli -> container -> adapters -> application -> domain`.
  Higher layers may import lower layers, never the other way around.
- `domain/` uses the standard library and `ecuador_lakehouse.domain` only.
  It must not import `config` or `logging_setup` either.
- `application/` defines ports as `typing.Protocol` and talk to adapters only
  through them. It may not import `adapters/`, `config`, `logging_setup`,
  `duckdb`, `dbt`, `httpx`, `jinja2`, `typer` or `rich`.
- Adapter subpackages (`sources`, `parsers`, `warehouse`, `transform`,
  `artifact`, `report`, `docs`) are independent of each other.
- Enforcement has two independent mechanisms:
  1. import-linter contracts in `pyproject.toml` (`layers`, `forbidden`,
     `independence`) run by `uv run lint-imports`, by `scripts/dev.py check`
     and by CI;
  2. an AST scan in `tests/architecture/test_layers.py` proving that every
     import under `domain/` resolves to the standard library or to
     `ecuador_lakehouse.domain`, and that `application/` does not import its
     forbidden modules. The scan has self-tests that plant a violating file in
     a temporary package, so the guard cannot silently stop working.
- Patterns named in `docs/ARCHITECTURE.md`: Ports & Adapters, Strategy for
  parsers/decoders/fetchers, Factory/Composition root in `container.py`,
  Repository for the batch ledger, Unit of Work for partition loads,
  Pipeline/DAG with Template-Method steps, frozen-dataclass value objects, and
  custom generic tests as executable specifications.

## Consequences

- Domain tests run in milliseconds and need no fixtures beyond Python values.
- Swapping HTTP for the bundled sample, or DuckDB for another warehouse, changes
  only adapters and the composition root.
- The two enforcement mechanisms overlap on purpose: import-linter understands
  transitive and external imports; the AST scan is explicit, fast to diagnose
  and impossible to satisfy through clever re-exports.
- New adapter subpackages must be added to the independence contract before
  they can import each other; that friction is intentional.
- Some boilerplate is unavoidable (ports, wiring). It is concentrated in
  `container.py` instead of being spread across use cases.
- `config.py` and `logging_setup.py` sit outside the layers because they are
  cross-cutting; the forbidden contracts keep them out of the inner two layers.

## Alternatives considered

- **Plain package layout with code review**: unverifiable, and the standard
  explicitly asks for an automated dependency test.
- **A dependency-injection framework**: extra dependency and runtime magic for a
  small CLI; an explicit composition root is easier to read and test.
- **Single enforcement tool**: import-linter alone misses the "standard library
  only" rule for non-external imports; the AST test alone would not model the
  layer order or adapter independence.
