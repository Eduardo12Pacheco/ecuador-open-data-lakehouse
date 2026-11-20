with tax as (

    select
        period_year,
        cast(sum(collected_usd) as decimal(18, 2)) as sri_collection_usd,
        cast(count(distinct period_month) as integer) as months_available
    from {{ ref('fct_tax_collection') }}
    group by period_year

),

gdp as (

    select * from {{ ref('int_gdp_annual') }}

)

select
    tax.period_year,
    tax.sri_collection_usd,
    gdp.gdp_current_usd,
    case
        when gdp.gdp_current_usd is null or gdp.gdp_current_usd = 0 then null
        else cast(tax.sri_collection_usd / gdp.gdp_current_usd as double)
    end as ratio,
    coalesce(gdp.quarters_available, 0) as quarters_available,
    tax.months_available,
    coalesce(gdp.quarters_available, 0) = 4 and tax.months_available = 12 as is_complete
from tax
left join gdp
    on gdp.period_year = tax.period_year
order by tax.period_year
