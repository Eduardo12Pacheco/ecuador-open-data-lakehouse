-- Reconciliation guard: the monthly mart must add up to the fact per year.
with mart as (

    select period_year, sum(nominal_usd) as total_usd
    from {{ ref('mart_tax_collection_monthly') }}
    group by period_year

),

fact as (

    select period_year, sum(collected_usd) as total_usd
    from {{ ref('fct_tax_collection') }}
    group by period_year

)

select
    coalesce(mart.period_year, fact.period_year) as period_year,
    mart.total_usd as mart_total_usd,
    fact.total_usd as fact_total_usd
from mart
full outer join fact
    on fact.period_year = mart.period_year
where mart.total_usd is null
   or fact.total_usd is null
   or abs(mart.total_usd - fact.total_usd) > 0.02
