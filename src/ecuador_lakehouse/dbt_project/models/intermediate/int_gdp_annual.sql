with gdp as (

    select
        fact.period_year,
        fact.period_quarter,
        fact.value_thousand_usd
    from {{ ref('fct_national_accounts') }} as fact
    inner join {{ ref('dim_national_account_item') }} as items
        on items.account_item_key = fact.account_item_key
    where items.account_code = 'IVAB3'
      and fact.price_basis = 'current'

)

select
    period_year,
    cast(sum(value_thousand_usd) as bigint) as gdp_thousand_usd,
    cast(sum(value_thousand_usd) * 1000 as decimal(20, 2)) as gdp_current_usd,
    cast(count(distinct period_quarter) as integer) as quarters_available
from gdp
group by period_year
order by period_year
