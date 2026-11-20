# Published artifact

`lakehouse publish --out DIR` turns the marts into a versioned, self-describing
data product that another project can consume without installing this package.
`lakehouse build --publish --out DIR` runs the full pipeline and publishes after
the quality gate. `lakehouse verify DIR` re-checks the result and exits 8 on any
inconsistency.

The artifact is a directory, not a service and not a database server: it can be
zipped, attached to a GitHub Release, copied to a USB drive or read directly
from a sibling project.

## Layout

```text
DIR/ecuador-lakehouse-1.0.0/
├── ecuador_lakehouse.duckdb   # schemas marts + meta only
├── parquet/
│   ├── dim_date.parquet
│   ├── ...                    # one ZSTD Parquet file per published table
│   └── mart_tax_lifecycle.parquet
├── manifest.json              # deterministic metadata, no wall-clock fields
├── SHA256SUMS                 # one SHA-256 per payload file
└── ATTRIBUTION.md             # source URLs, licenses and modifications
```

The directory name is `<artifact_name>-<artifact_version>`. The current
artifact version is `1.0.0` and equals the contract version; it is independent
of the Python package version. The database exposes only `marts` (the public
tables) and a small `meta.build_info` table (build time, artifact version,
generator, data mode). Build time never participates in a fingerprint.

The published tables are the 7 conformed dimensions, 3 facts and 4 analytic
marts listed in [ARCHITECTURE.md](ARCHITECTURE.md). The typed schema is
committed in `src/ecuador_lakehouse/artifact_contract.json` and explained in
[CONTRACT.md](CONTRACT.md).

## Manifest

`manifest.json` is validated by
[`docs/schemas/manifest.schema.json`](schemas/manifest.schema.json)
(JSON Schema draft 2020-12, `schema_version: "1.0"`). It contains no build
dates.

| Field | Meaning |
| --- | --- |
| `schema_version` | Manifest schema version, currently `"1.0"` |
| `artifact_name` | `ecuador-lakehouse` |
| `artifact_version` | Semver data-product version; equals the contract version |
| `generator` | `ecuador-open-data-lakehouse/<package version>` |
| `duckdb_version` | DuckDB version that wrote the artifact |
| `dbt_core_version` | dbt-core version that built the marts |
| `data_mode` | `sample` or `full` |
| `built_from` | Per-source `{source_id, url, license_id, files:[{name, sha256}]}` |
| `tables` | One entry per published table |
| `quality` | `{tests_total, tests_passed, unit_tests_total, unit_tests_passed}` |
| `attribution` | The full attribution text, also written to `ATTRIBUTION.md` |

Each `tables` entry has:

| Field | Meaning |
| --- | --- |
| `name`, `schema` | Table name and schema (`marts`) |
| `kind` | `dim`, `fct` or `mart` |
| `grain` | Human-readable grain, mirrored from the contract |
| `row_count` | Exact row count at publish time |
| `columns` | Ordered `{name, type, description}` triples |
| `content_sha256` | Logical fingerprint of the table |
| `parquet_file` | Relative path such as `parquet/dim_date.parquet` |

`content_sha256` is the SHA-256 of the bytes produced by
`COPY (SELECT * FROM <table> ORDER BY ALL) TO <file> (FORMAT CSV)`. It
normalizes row order and ignores DuckDB/Parquet file metadata, so two builds
from the same inputs and data mode agree even though the database and Parquet
bytes do not. That is the determinism guarantee: two fresh sample builds
produce equal `content_sha256` values for all 14 tables.

## Consuming with DuckDB

Open the database read-only. `ATTACH` is useful when the consumer already has a
connection with its own tables:

```sql
ATTACH 'DIR/ecuador-lakehouse-1.0.0/ecuador_lakehouse.duckdb'
    AS lakehouse (READ_ONLY);

SELECT tax_group_name, sum(nominal_usd) AS total_usd
FROM lakehouse.marts.mart_tax_collection_monthly
WHERE period_year = 2025
GROUP BY tax_group_name
ORDER BY total_usd DESC
LIMIT 5;
```

From Python, with only the `duckdb` dependency:

```python
import duckdb

database = artifact_dir / "ecuador_lakehouse.duckdb"
with duckdb.connect(str(database), read_only=True) as con:
    rows = con.execute(
        """
        SELECT period_year, ratio
        FROM marts.mart_tax_to_gdp_annual
        WHERE is_complete
        ORDER BY period_year DESC
        LIMIT 1
        """
    ).fetchall()
```

Use `ATTACH ... (READ_ONLY)` instead when you already have a connection with
your own tables, as in the SQL example above.

The complete runnable example is
[`examples/consume_artifact.py`](../examples/consume_artifact.py). It imports
only `duckdb` and the standard library, prints the top five tax groups of the
latest year and the latest complete SRI/GDP ratio, and is exercised by a test
that asserts it does not import `ecuador_lakehouse`.

Parquet files can be read without the DuckDB database:

```sql
SELECT * FROM read_parquet('DIR/ecuador-lakehouse-1.0.0/parquet/mart_inflation_monthly.parquet');
```

## Verifying an artifact

```bash
lakehouse verify DIR/ecuador-lakehouse-1.0.0
```

Verification is intentionally redundant. It checks:

1. `manifest.json` parses and is internally consistent.
2. Every expected file exists: the database, `manifest.json`,
   `ATTRIBUTION.md` and one Parquet file per table; no unlisted file is present.
3. `SHA256SUMS` covers every payload file and every byte matches its recorded
   SHA-256.
4. Each Parquet row count and column type list matches the manifest.
5. The DuckDB file has a `marts` schema and no `raw`, `staging` or
   `intermediate` schema.
6. The DuckDB table set, ordered columns and row counts match the manifest.
7. Each table's logical `content_sha256` matches the manifest.

A missing table, a flipped byte, a schema change or a manifest edit fails with
`ArtifactVerificationError` and exit code 8. Verification needs only the
artifact directory and DuckDB; it does not read the warehouse.

## Version compatibility

Two versions move independently:

- **Package version** (`0.1.1`) describes the software: CLI, parsers, report
  and dbt project.
- **Artifact version** (`1.0.0`) describes the data product and equals the
  contract version.

Consumers should pin the artifact version they tested and check
`manifest.json.schema_version` before parsing the manifest. The semver meaning
of `artifact_version` is defined in [CONTRACT.md](CONTRACT.md): a MAJOR bump
means a table or column was removed or renamed, or a type changed; a MINOR bump
adds something; a PATCH bump fixes data without changing the schema.

The manifest also records `duckdb_version` and `dbt_core_version`, so a consumer
can reproduce or diagnose a build. `data_mode` matters: the bundled `sample` is
province grain, while `full` keeps canton detail.

## Licensing and redistribution

The artifact contains derived data, not code. `ATTRIBUTION.md` lists the
publisher, source URL, license and modifications for SRI, INEC and BCE. SRI and
BCE data are CC BY; INEC is CC BY 4.0. Only CC BY / CC BY 4.0 sources are
included, so the artifact is redistributable with attribution. Non-commercial
BCE datasets are intentionally excluded ([ADR 0004](adr/0004-sample-strategy-and-licensing.md)).
