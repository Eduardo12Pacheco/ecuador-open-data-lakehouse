# Artifact contract and versioning

The published artifact is a public interface. `artifact_contract.json` records
the tables, grains and typed columns that consumers are allowed to rely on, and
`lakehouse contract check` compares that committed contract with the schema
actually materialized in the warehouse.

The current contract is version **1.0.0** and describes 14 tables: 7 dimensions,
3 facts and 4 analytic marts. The artifact version equals the contract version.

## File

`src/ecuador_lakehouse/artifact_contract.json` ships inside the wheel. Its shape
is:

```json
{
  "schema_version": 1,
  "contract_version": "1.0.0",
  "artifact_name": "ecuador-lakehouse",
  "tables": [
    {
      "name": "dim_date",
      "kind": "dim",
      "grain": "month",
      "columns": [
        {"name": "month_key", "type": "INTEGER"},
        {"name": "month_start_date", "type": "DATE"}
      ]
    }
  ]
}
```

`kind` is one of `dim`, `fct` or `mart`. `grain` is a human-readable
description of one row. `columns` is ordered and every type is the DuckDB type
the model must produce.

Only the marts are contracted. Staging and intermediate models, the raw layer,
the report site and the manifest schema are not part of this interface:
consumers get the marts and the manifest.

## Semver rules

The artifact version uses semantic versioning. The rules are about what a
consumer can observe: tables, columns, types and the meaning of a value.

| Change | Kind | Required bump |
| --- | --- | --- |
| Remove a table | breaking | **MAJOR** |
| Rename a table | breaking (old name disappears) | **MAJOR** |
| Remove a column | breaking | **MAJOR** |
| Rename a column | breaking (old name disappears) | **MAJOR** |
| Change a column type (for example `INTEGER` to `BIGINT`) | breaking | **MAJOR** |
| Change a table grain or the meaning/unit of a column | breaking by policy | **MAJOR** |
| Add a table | additive | **MINOR** |
| Add a column | additive | **MINOR** |
| Add an allowed value or extend coverage without changing the schema | additive | **MINOR** |
| Fix a bug, backfill wrong rows or improve descriptions with no schema change | fix | **PATCH** |

A `MINOR` bump is safe for a consumer that selects named columns: existing
columns stay present with the same names and types. A `MAJOR` bump requires the
consumer to update its queries. A `PATCH` bump requires no change.

`contract check` performs the mechanical part of that table:

```text
committed table missing in warehouse    -> BREAKING: table <name> removed
committed column missing                -> BREAKING: <table>.<column> removed
committed column type differs           -> BREAKING: type changed from A to B
warehouse table absent from contract    -> ADDITIVE: table <name> added
warehouse column absent from contract   -> ADDITIVE: <table>.<column> added
```

When any breaking entry exists the required bump is MAJOR; otherwise any
additive entry requires MINOR; otherwise no bump is required. The command exits
8 whenever the diff is non-empty, because the committed contract no longer
describes the warehouse. Update the contract (and bump it following the rules)
until `contract check` is clean again.

Grain and semantic changes are not machine-detectable from
`information_schema`, so they remain a review responsibility. They still follow
the MAJOR rule: a consumer that sums `collected_usd` per month must not silently
receive a different unit or a different row meaning.

## How to change the contract

1. Change the dbt model and its enforced contract, then rebuild and test with
   `lakehouse build`.
2. Run `lakehouse contract check`. Read the reported breaking and additive
   entries. Decide the required level with the table above.
3. Edit `src/ecuador_lakehouse/artifact_contract.json`: update
   `contract_version` and the affected `tables`, `grain` or `columns` entries.
   The artifact version is read from this file, so the published directory and
   the manifest move together.
4. Re-run `lakehouse build` and `lakehouse contract check`; it must report that
   the committed version matches the warehouse tables.
5. Publish and verify:
   `lakehouse publish --out dist-artifact` and
   `lakehouse verify dist-artifact/ecuador-lakehouse-<version>`.
6. Record the reason and the bump in `CHANGELOG.md` and in the pull request.
   A breaking change may also need a migration note for known consumers.

The contract version is independent of the package version. A parser bug fix
can ship package `0.1.1` while the data product stays `1.0.0`; adding a mart
column can move the data product to `1.1.0` without a package release if the
data are republished from the same code.

## Verification and compatibility

Two different checks exist and are not interchangeable:

- `lakehouse contract check` compares the **committed contract** with the
  **current warehouse schema**. It answers "is this build allowed to keep the
  published interface?" and runs before publishing.
- `lakehouse verify DIR` checks an **already published artifact** against its
  own manifest, checksums and logical fingerprints. It answers "is this
  directory intact?" and does not read the warehouse.

A consumer should:

1. verify the artifact once with `lakehouse verify DIR`;
2. read `manifest.json` and check `schema_version == "1.0"`;
3. pin the artifact `MAJOR` version and the exact table/column names it uses;
4. treat a new `MINOR` as backward compatible and a new `MAJOR` as a migration.

The manifest schema itself is versioned by `schema_version`. A future change to
the manifest field set is a separate contract: it would bump
`schema_version`, and consumers must check it before assuming fields exist.

See [ARTIFACT.md](ARTIFACT.md) for the payload layout and the verification
steps, and [ADR 0007](adr/0007-artifact-contract-and-versioning.md) for the
decision record.
