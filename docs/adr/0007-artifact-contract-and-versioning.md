# ADR 0007 - Published artifact, contract versioning and determinism

## Status

Accepted (2026-11-20, task T11).

## Context

The lakehouse must hand a stable data product to other projects. Consumers need
to know which tables, columns and types they can rely on, must be able to verify
that a downloaded artifact is intact, and must be able to reason about
compatibility when the data product evolves. At the same time two builds from
the same inputs must produce identical table contents so published artifacts can
be compared byte-for-byte at the logical level (S14, S15, D19).

DuckDB database files and Parquet files embed build-specific metadata and are
not byte-reproducible, so file hashes cannot serve as the determinism
fingerprint. Wall-clock timestamps in marts would have the same problem: they
make every build differ for reasons unrelated to the data.

## Decision

1. **Artifact layout.** `lakehouse publish --out DIR` writes
   `DIR/ecuador-lakehouse-<artifact_version>/` with a DuckDB file that contains
   only the `marts` and `meta` schemas, one ZSTD Parquet file per published
   table, a deterministic `manifest.json`, a `SHA256SUMS` file and
   `ATTRIBUTION.md`.
2. **Logical fingerprint.** Every table gets a `content_sha256`: the SHA-256 of
   the bytes produced by
   `COPY (SELECT * FROM <table> ORDER BY ALL) TO <file> (FORMAT CSV)`. This
   normalizes row order and ignores file-level metadata, so it is stable across
   two builds with the same data.
3. **No wall-clock in the data product.** Marts contain no timestamps and the
   manifest contains no build dates. The only build time lives in
   `meta.build_info` inside the published DuckDB file and is excluded from every
   `content_sha256` and from `SHA256SUMS`.
4. **Two versions.** The package version describes the software; the artifact
   version equals the contract version and describes the data product. They
   move independently (a bug fix can ship a patch release without changing the
   data contract).
5. **Committed contract.** `artifact_contract.json` lists every published
   table with its kind, grain and typed columns. `lakehouse contract check`
   reads the schema actually materialized in the warehouse and compares it with
   the committed contract: a removed table or column, or a changed type, is a
   breaking change that requires a MAJOR bump; an added table or column is
   additive and requires a MINOR bump. A pure fix requires a PATCH bump.
6. **Verification.** `lakehouse verify DIR` reparses the manifest, checks every
   `SHA256SUMS` entry, recomputes each table's logical fingerprint from the
   artifact DuckDB file, compares manifest, DuckDB and Parquet row counts and
   schemas, and exits with code 8 on any mismatch.

## Consequences

- Consumers can pin `artifact_version` and use the manifest to discover tables,
  grains and column types without opening the database.
- Tampering with a Parquet file, the DuckDB file, the manifest or removing a
  file is detected and mapped to exit code 8.
- Adding a column forces a MINOR version bump and raises the published
  artifact version; changing a type or removing anything forces a MAJOR bump.
- Publishing is not byte-identical at the file level, but two sample builds
  produce equal `content_sha256` values for all 14 tables, which is the
  determinism guarantee the project advertises.
- The contract intentionally does not cover staging or intermediate models:
  only the marts are a public interface.

## Alternatives considered

- **Hash the `.duckdb` and Parquet files for determinism.** Rejected: both
  formats embed metadata that changes between runs even with identical data.
- **Use dbt model versions instead of a committed contract.** Rejected: dbt
  versions describe model interfaces inside the project, not the published
  artifact that sibling repositories consume.
- **Publish a single Parquet directory without DuckDB.** Rejected: DuckDB gives
  consumers joins and SQL over the whole product with one dependency, and the
  per-table Parquet files keep partial consumption cheap.
