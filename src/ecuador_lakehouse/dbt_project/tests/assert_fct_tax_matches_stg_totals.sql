-- Reconciliation guard: the incremental fact must preserve the staging totals.
with fact as (

    select period_year, sum(collected_usd) as total_usd
    from {{ ref('fct_tax_collection') }}
    group by period_year

),

staging as (

    select period_year, sum(collected_usd) as total_usd
    from {{ ref('stg_sri__tax_collection') }}
    group by period_year

)

select
    coalesce(fact.period_year, staging.period_year) as period_year,
    fact.total_usd as fact_total_usd,
    staging.total_usd as staging_total_usd
from fact
full outer join staging
    on staging.period_year = fact.period_year
where fact.total_usd is null
   or staging.total_usd is null
   or abs(fact.total_usd - staging.total_usd) > 0.02
