# Data sources, lineage and limitations

This page records where the data comes from, how it is verified, what the
bundled sample contains and what the numbers can and cannot claim. The source
of truth for acquisition is `src/ecuador_lakehouse/sources.lock.json`; the
source of truth for the bundled files is
`src/ecuador_lakehouse/sample_data/SAMPLE_MANIFEST.json`.

## Sources

All sources were verified on 2026-11-19 without an account, key or browser
session, with the same User-Agent the fetcher sends. Every upstream file is
pinned by size and SHA-256 in `sources.lock.json`; downloads are restricted to
the hosts below.

| Source | Publisher | URL | Format | License | Partition |
| --- | --- | --- | --- | --- | --- |
| SRI tax collection | Servicio de Rentas Internas | `https://descargas.sri.gob.ec/download/datosAbiertos/sri_recaudacion_<YYYY>.csv` | `\|`-delimited, one file per year 2017–2026 | CC BY (`license_id: cc-by` in CKAN) | yearly |
| INEC consumer price index | Instituto Nacional de Estadística y Censos | `https://www.ecuadorencifras.gob.ec/documentos/web-inec/Inflacion/2024/Diciembre/Tabulados_y_series_historicas_CSV.zip` | nested ZIP with 12 wide CSV files, cp1252 | CC BY 4.0 (stated on the IPC page) | `2024-12` |
| BCE national accounts | Banco Central del Ecuador | `https://www.datosabiertos.gob.ec/dataset/7d5ad4b3-a8f7-42d9-8103-81336a592ea6/resource/2fe2427a-daeb-4137-a29f-22834f3d5ee0/download/cuentastrimestralesdesagregadas.csv` | `;`-delimited CSV, cp1252, CRLF | CC BY (`license_id: cc-by` in CKAN) | frozen 2000Q1–2021Q1 |

The CKAN API `https://www.datosabiertos.gob.ec/api/3/action/package_show?id=<dataset>`
is used only as license evidence; its recorded fixtures live in
`tests/fixtures/ckan/`. No catalogue response is required at build time.

### Pinned files

These are the twelve files the lockfile pins. Sizes are bytes; SHA-256 values
are of the upstream bytes. Only the current SRI year is mutable, because SRI
refreshes it monthly.

| File | Bytes | SHA-256 | Mutable |
| --- | ---: | --- | --- |
| `sri_recaudacion_2017.csv` | 84,892,997 | `dd14c281d082417342daa2e3060ba1df759f2c29a2f7144e4ce91e62a79753d4` | no |
| `sri_recaudacion_2018.csv` | 90,751,274 | `5159954189b7e771b45e8a8f39dced83c1ea555a2044e277ad92dc9a8a4c40a2` | no |
| `sri_recaudacion_2019.csv` | 95,526,741 | `2d109fe8c4419086c17ae11c74095a87d7bb30a3bfe90f6aa1445700ffd475df` | no |
| `sri_recaudacion_2020.csv` | 84,746,785 | `20e51bafc4cb4d49edacc6ee346bff7a5fcc2237bbc8f041163dc3bab65b1903` | no |
| `sri_recaudacion_2021.csv` | 101,639,183 | `bf088d16738ab9e4bca10803155680e80564107f320034e8c8b37ebd200845fe` | no |
| `sri_recaudacion_2022.csv` | 108,707,735 | `7a7f106f64cf0070377b4898c06907bdc50c293763050630bc742601d30b1b69` | no |
| `sri_recaudacion_2023.csv` | 100,356,033 | `e6e80b5cdbae088e7ab4f4e4be3b30b75faf1df81edeb4cca2c3f52001f10c51` | no |
| `sri_recaudacion_2024.csv` | 96,066,889 | `f5ffc07af3666084f2de1904ae198f3b48d9fe219176ca7039109e4d3040e173` | no |
| `sri_recaudacion_2025.csv` | 100,563,014 | `d6ec28197b6b85f2ce05cf12c076d34556e7c99cff49e4ad6d0995639fed1c4d` | no |
| `sri_recaudacion_2026.csv` | 83,320,465 | `90878717f7faadaf5f3e815ca35c6164b059ae97b7ef8b8722e7b843918b420f` | **yes** |
| `Tabulados_y_series_historicas_CSV.zip` | 7,479,409 | `e7b854b4f422d23f622e3c474ebc47a0bc46caa9d15f0a3670bce7f67fc697f4` | no |
| `cuentastrimestralesdesagregadas.csv` | 6,108,986 | `b90e0e5a403a44ecd862969b72c6fc900f730e62d7b4cffecaa55116ed81e187` | no |

### Format quirks handled by the parsers

- **SRI** is UTF-8 with a BOM for 2017–2022 and cp1252 for 2023–2026. Files are
  `|`-delimited, months are labels such as `01 Enero`, amounts use a decimal
  comma (`83,3100`), and `CANTON` is absent in older files. Extra real-file
  columns (`GRAN_CONTRIBUYENTE`, `CODIGO_OPERA_FAMILIA`) are ignored only after
  the required header is validated. Missing required columns and unknown
  headers raise `SourceSchemaError` (exit 4).
- **BCE** is cp1252 with `;` delimiters and CRLF, amounts use comma thousands
  separators, empty values are preserved as empty strings, and negative values
  are valid.
- **INEC** is a ZIP inside a ZIP inside a ZIP. Each of the 12 CSVs has four
  title rows, a `Nivel` header, 120 Spanish month columns (`ene-15`…`dic-24`),
  three footer rows, and mixed decimals (`1,000000` and `0.224503124`). The
  parser discovers the header, stops at the footer and melts the months to long
  rows.

Decoding policy D13 is strict: try `utf-8-sig`, then `cp1252`; never ignore
bytes. If both fail the parser raises `SourceSchemaError`.

## Bundled sample

`lakehouse build` defaults to `--mode sample` and reads only the wheel. The
sample is real data, deterministically reduced:

- SRI files are aggregated to `ANIO, MES, GRUPO, SUBGRUPO, IMPUESTO,
  TIPO_CONTRIBUYENTE, PROVINCIA` with `Decimal` half-up rounding to cents. The
  province grain drops canton and operator-family detail while preserving every
  group total within one cent.
- BCE bytes are bundled verbatim inside gzip, so the decompressed SHA-256 equals
  the pinned upstream checksum.
- The 12 INEC index CSVs are copied verbatim into one flat ZIP with fixed
  timestamps and deterministic ordering.

The bundle is about 4.15 MB (budget: 8,000,000 bytes) and contains 12 files.
Row counts:

| Partition | Rows |
| --- | ---: |
| SRI 2017 | 22,679 |
| SRI 2018 | 22,777 |
| SRI 2019 | 24,035 |
| SRI 2020 | 23,839 |
| SRI 2021 | 25,260 |
| SRI 2022 | 25,889 |
| SRI 2023 | 25,519 |
| SRI 2024 | 24,423 |
| SRI 2025 | 25,348 |
| SRI 2026 (Jan–Oct) | 21,548 |
| BCE national accounts | 32,470 |
| INEC CPI (long rows after melt) | 911,520 |

`lakehouse doctor` re-verifies every bundled file against
`SAMPLE_MANIFEST.json`. The maintainer command `lakehouse sample build` rebuilds
the bundle from the pinned upstream files and is not part of a normal build.
The sample reduction and its licensing rationale are recorded in
[ADR 0004](adr/0004-sample-strategy-and-licensing.md).

## Measured facts

These numbers are measured from the verified files and are used by tests and
the report. They are not projections.

- SRI yearly collection (USD millions): 2019 14,268.8; 2020 12,381.8; 2021
  13,976.2; 2022 17,161.8; 2023 17,419.7; 2024 20,131.3; 2025 21,500.9;
  2026 Jan–Oct 20,763.9. The 2025 figure matches the published headline of
  about USD 21,501 million.
- The SRI history contains 244 distinct normalized tax lines across
  2017–2026, with 135–173 present per year, 83 present in all ten years, 109
  introduced after 2017, 102 retired before 2026 and 62 with gaps. The SCD2
  natural key is tax x subgroup, which yields 245 combinations (one tax line
  legitimately belongs to two subgroups). No group or subgroup
  reclassification was observed (0 of 244 lines).
- BCE national accounts contain 85 quarters (2000Q1–2021Q1), 45 industries,
  GDP aggregates and two price bases; 176 values are empty and 32,470 rows
  cover the product of quarters, bases and 191 codes.
- INEC national CPI: 633 item rows x 120 months (January 2015 to December 2024),
  base 2014 = 100. The general index in January 2015 is 101.24.

The control totals used by the reconciliation tests live in
`src/ecuador_lakehouse/dbt_project/seeds/control_totals.csv`; they are generated
from the full upstream files, never hand-edited.

## Lineage

```text
sources.lock.json + sample manifest
        |
        v
raw.sri_tax_collection / raw.bce_cnt_quarterly / raw.inec_cpi_index
  (+ meta.batches)
        |
        v
staging: stg_sri__tax_collection, stg_bce__national_accounts,
         stg_inec__cpi_index
        |
        v
intermediate: int_tax_item_year_presence, int_tax_item_versions,
              int_tax_collection_monthly, int_cpi_national_monthly,
              int_gdp_annual
        |
        v
marts: dim_date, dim_quarter, dim_geography, dim_tax_item, dim_price_area,
       dim_cpi_item, dim_national_account_item, fct_tax_collection,
       fct_cpi_index, fct_national_accounts, mart_tax_collection_monthly,
       mart_inflation_monthly, mart_tax_to_gdp_annual, mart_tax_lifecycle
```

The rendered model DAG is committed in [LINEAGE.md](LINEAGE.md) and regenerated
with `lakehouse docs --mermaid docs/LINEAGE.md`. Every model and column is
described in dbt; the published subset is described in
[ARTIFACT.md](ARTIFACT.md).

## Licenses and attribution

Code is MIT-licensed. Data keeps the publisher's license:

- SRI tax collection and BCE national accounts: Creative Commons Attribution
  (`cc-by`).
- INEC CPI: Creative Commons Attribution 4.0 International (CC BY 4.0).

The bundled sample and the published artifact ship `ATTRIBUTION.md` with the
publisher, source URL, license and modifications. Redistribution of derived
data is allowed with attribution. BCE datasets whose CKAN license is
non-commercial are deliberately excluded, even when reachable
([ADR 0004](adr/0004-sample-strategy-and-licensing.md)).

## Limitations

- **SRI is not total fiscal pressure.** The series covers taxes administered by
  SRI only. It excludes other public revenue, and the SRI/GDP ratio is a
  partial indicator, not a general tax-to-GDP measure. The macro mart exposes
  the ratio for complete years only.
- **CPI vintage cutoff.** The bundled INEC vintage ends in December 2024 with
  base 2014 = 100. A new base (July 2025–June 2026 = 100) started in 2026 and is
  out of scope. Deflated tax values therefore stop after 2024-12; later months
  keep nominal values.
- **BCE series ends in 2021Q1.** National accounts stop there, so only 2017,
  2018, 2019 and 2020 have four quarters and are marked `is_complete`. The 2021
  ratio is published for inspection but flagged incomplete; 2022 and later have
  no GDP denominator.
- **SCD2 limitation.** On real data, tax-line lifecycle is driven by
  introduction, retirement and gaps; no group or subgroup reclassification was
  observed in 2017–2026. Attribute changes are covered by dbt unit tests and a
  Hypothesis property test on the real model, not by the sample alone. An item
  retired before the latest loaded year keeps an open-ended inactive version;
  facts only join active versions, so this does not affect marts.
- **Sample grain.** The bundled sample is province grain, without canton detail
  and without operator-family columns. `full` mode keeps the cantons present in
  the upstream files, but the report and artifact stories are built on the
  sample.
- **No live freshness guarantee.** The current SRI year is mutable and is
  refreshed by SRI monthly. The bundle pins the snapshot observed on
  2026-11-19; `lakehouse fetch` can retrieve newer bytes, and accepting a new
  vintage is an explicit, recorded action.
- **Not included.** SRI series hosted only on an unreliable host, non-commercial
  BCE datasets, the 2026 IPC base and the World Bank API are out of scope. The
  project stays with three verified Ecuadorian sources.

## Reproducing the data layer

```bash
# Offline default: uses the bundled sample.
lakehouse build

# Check the bundle and the installation.
lakehouse doctor

# Maintainers only: download the pinned files once and rebuild the bundle.
lakehouse fetch --source sri --years 2025
lakehouse sample build --cache-dir "$LAKEHOUSE_HOME/cache"

# Regenerate lineage from a real dbt parse.
lakehouse docs --mermaid docs/LINEAGE.md
```

Downloads are cached under `$LAKEHOUSE_HOME/cache` and never committed. Large
upstream files stay out of git; only the reduced sample is versioned.
