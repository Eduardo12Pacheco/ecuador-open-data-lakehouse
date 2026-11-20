# ADR 0005 — SCD2 as a deterministic SQL model, not a dbt snapshot

## Status

Accepted (2026-11-20).

## Context

The tax catalogue changes every year: lines are introduced, retired, reappear
after a gap and (rarely) move between groups. The star schema needs
`dim_tax_item` to be slowly changing so a fact can point to the exact version
that was valid in its collection year (S10, D15). Two families of options exist:

1. **dbt snapshot** (`check`/`timestamp` strategy): dbt-managed history keyed by
   a unique key and an `updated_at` column. It is stateful: each run compares
   the current source rows against the previous snapshot table, writes new rows
   with `dbt_valid_from`/`dbt_valid_to`, and depends on wall-clock timestamps.
2. **SQL model**: rebuild the version islands from the current raw data on
   every run, deriving validity from data alone.

The source is a static yearly history rather than an append-only feed. There is
no `updated_at` column, and the bundled sample plus the full files are
re-downloaded or re-parsed as immutable partitions. A snapshot would mix run
history with data history, and two builds on a clean machine would not
necessarily agree if the snapshot table were reused.

## Decision

- **Implement SCD2 as SQL models over the full raw history.**
  `int_tax_item_year_presence` builds a dense presence matrix per tax natural
  key and loaded year; `int_tax_item_versions` computes gaps-and-islands over a
  generated yearly spine from each line's first presence to the latest loaded
  year. A version boundary is created whenever `(lifecycle_status,
  tax_group_name)` differs from the previous year.
- **Validity comes from data, never from the clock.** `valid_from` is
  January 1 of the island's first year, `valid_to` is December 31 of its last
  year, and the last island is open-ended (`9999-12-31`). `is_current` is exactly
  `valid_to = 9999-12-31`. There is one current row per natural key by
  construction.
- **Natural key is `(norm(IMPUESTO), norm(SUBGRUPO_IMPUESTO))`** per D15; the
  group is a tracked attribute, so a group change starts a new version while
  the display names are taken from the most recent year the line was present.
- **Facts join point-in-time.** `fct_tax_collection` joins versions on the
  natural key where the fact year is inside `[valid_from, valid_to]` and the
  version is active. A fact can never point to an inactive version or to a
  version outside its validity window.
- **Property-tested against the real model.** A Hypothesis test loads random
  presence/group matrices into a temporary warehouse, runs `+dim_tax_item`
  through the real dbt runner and checks one current version per key, contiguous
  non-overlapping ranges, and exactly one active version for every present
  `(item, year)` inside the loaded span.
- **Surrogate keys are deterministic.** `tax_item_key` is
  `md5(tax_item_nk || '||' || valid_from)`, consistent with D11 and S15, so two
  builds produce the same keys.

## Consequences

- Positive: deterministic and replay-free; a full rebuild reproduces the same
  dimension and keys; no stateful snapshot table to reconcile; validity is
  derivable from the data alone, which the property test exercises.
- Positive: the version boundary definition is explicit SQL that can be unit
  tested in dbt (continuous, gap, retirement, reclassification, late
  introduction) rather than hidden in dbt internals.
- Negative: a true source history edit (as opposed to a new yearly partition)
  rewrites the affected history on the next build. That is the intended
  semantic: the raw layer is the source of truth.
- Negative: "inactive until the latest loaded year" means an item retired before
  the last loaded year keeps an open-ended inactive version. This is harmless
  because facts only join active versions, and it preserves one current row per
  key.
- Measured on the bundled sample: 245 natural keys, one current version per key,
  no group changes in 2017–2026, so the real-data behaviour is dominated by
  introduction/retirement/gaps as documented in D14.

## Alternatives considered

- **dbt snapshot (`check` strategy)**: rejected because the source has no
  `updated_at` column, snapshots are stateful and run-history dependent, and
  two clean builds would diverge if the snapshot table were reused. The
  deterministic SQL model rebuilds versions from raw data instead.
- **`row_number()`-generated surrogate keys**: rejected because row order is not
  part of the data contract; D11 requires hash-based keys so builds agree.
- **A hand-maintained version history seed**: rejected because it would drift
  from the raw files and could not be property-tested against the real model.
