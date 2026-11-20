-- Sanity guard: only complete years are compared, and the ratio is plausible.
select
    period_year,
    sri_collection_usd,
    gdp_current_usd,
    ratio
from {{ ref('mart_tax_to_gdp_annual') }}
where is_complete
  and (ratio is null or ratio < 0.05 or ratio > 0.25)
