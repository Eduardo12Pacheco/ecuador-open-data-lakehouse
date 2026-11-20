-- Control-total reconciliation for the frozen SRI years (tolerance 500 USD).
with actual as (

    select period_year, sum(collected_usd) as total_usd
    from {{ ref('fct_tax_collection') }}
    group by period_year

)

select
    control_totals.period_year,
    control_totals.expected_total_usd,
    actual.total_usd as actual_total_usd
from {{ ref('control_totals') }} as control_totals
inner join actual
    on actual.period_year = control_totals.period_year
where control_totals.is_frozen
  and abs(actual.total_usd - control_totals.expected_total_usd) > 500
