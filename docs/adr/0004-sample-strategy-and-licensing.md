# ADR 0004 — Bundled sample strategy and licensing

## Status

Accepted (2026-11-20).

## Context

`lakehouse build` must work fully offline with zero keys (S2) while the real
inputs total roughly 960 MB across twelve files. Shipping those bytes in the
wheel would be unacceptable, and shipping arbitrary synthetic rows would break
the promise that the sample is real data whose totals reconcile with published
figures. The published artifact must also be redistributable (S14), which rules
out datasets whose CKAN license is non-commercial.

The three sources behave differently. SRI ships ten 83–109 MB yearly CSVs at
province/canton grain; only an aggregated slice is useful for a lightweight
example. BCE ships one frozen 6 MB file that is already small. INEC ships a
nested archive whose twelve index CSVs are the payload the parser needs.

## Decision

- **Only redistributable sources are bundled.** SRI (`cc-by`), BCE (`cc-by`)
  and INEC (CC BY 4.0 on the publisher page) are included. BCE datasets whose
  CKAN license is `cc-nc` (monthly information, 2024 national accounts,
  interest rates) are excluded from the pipeline and the artifact, even though
  they are technically reachable. The published data product therefore remains
  redistributable under CC BY.
- **The SRI sample is a deterministic reduction, not synthetic data.** Rows are
  grouped by `ANIO, MES, GRUPO_IMPUESTO, SUBGRUPO_IMPUESTO, IMPUESTO,
  TIPO_CONTRIBUYENTE, PROVINCIA`, `VALOR_RECAUDADO` is summed with
  `decimal.Decimal` and rounded half-up to cents, and canton, `GRAN_CONTRIBUYENTE`
  and `CODIGO_OPERA_FAMILIA` are dropped. This matches D10: about 22,700–25,900
  rows and roughly 0.2 MB per year, while every total is preserved within one
  cent per group.
- **BCE is bundled verbatim.** The upstream bytes are placed unchanged inside a
  gzip container, so the decompressed SHA-256 equals the pinned upstream
  checksum and tests can prove it.
- **INEC is repacked, not modified.** The twelve index CSVs are copied
  verbatim out of the nested archives into one flat ZIP with fixed timestamp
  `1980-01-01`, deterministic ordering and deflate compression. The parser
  handles the flat archive through the same member matcher.
- **Byte reproducibility is a requirement.** Gzip writers use `mtime=0` and no
  filename; ZIP entries use a fixed timestamp. The manifest contains no build
  timestamp, only the pinned inventory `checked_at`, the builder version, and
  per-file size/SHA-256/row count/derived-from SHA-256. Two runs therefore
  produce identical bytes.
- **Control totals are generated from the full upstream files**, one row per SRI
  year in `dbt_project/seeds/control_totals.csv`; the current year is marked
  `is_frozen=false`. They are the reconciliation anchor for the dbt singular
  tests and are not hand-edited.
- **The sample is verified like any other source.** `SAMPLE_MANIFEST.json` is
  the contract: `SampleSourceFetcher` verifies size and SHA-256 before copying a
  file into the cache, and `lakehouse doctor` re-verifies all twelve files.
- **Large upstream files stay out of git.** Downloads go to
  `$LAKEHOUSE_HOME/cache` (or `--cache-dir` for the maintainer command) outside
  the repository; a second run reuses them. Only the generated sample
  (about 4.1 MB) is committed.

## Consequences

- `lakehouse build` never needs the network in the default `sample` mode, and
  the artifact and report can be reproduced by anyone with the wheel.
- The sample stays under the 8,000,000-byte budget while preserving real tax
  totals, the real BCE series and the real CPI matrix.
- Tests assert exact SRI row counts, the BCE decompressed checksum, the INEC
  row count and control-total tolerances, so a silent change in the reduction
  or in an upstream file is caught.
- Generating the sample is a maintainer action (`lakehouse sample build`); it
  downloads the pinned files once, needs outbound HTTPS and is not part of
  `lakehouse build`.
- The current SRI year is mutable by nature. The builder records the observed
  SHA-256 in the manifest, and tests pin the bundled snapshot rather than the
  live checksum (L4); changing the bundle is an explicit `chore(data)` commit.
- Province grain loses canton detail in `sample` mode. `full` mode keeps
  cantons, and the bundled sample is documented as province grain.

## Alternatives considered

- **Synthetic fixtures**: fast to generate but dishonest for a data-engineering
  portfolio; totals would not reconcile to published figures.
- **Bundle the full 960 MB**: contradicts the wheel size and offline-first
  installation story; the artifact would be unusable.
- **Aggregate to national grain only**: smaller, but it would drop the province
  dimension that the report and the geography relationships test need.
- **Keep the nested INEC archive**: preserves upstream shape but requires the
  parser to redo archive discovery on every build; the flat ZIP is simpler and
  still contains the same verbatim CSV bytes.
- **Include `cc-nc` BCE datasets**: rejected for licensing hygiene (D9), even
  though the extra series would make the macro mart richer.
