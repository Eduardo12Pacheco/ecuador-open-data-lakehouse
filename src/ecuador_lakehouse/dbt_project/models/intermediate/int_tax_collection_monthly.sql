with fact as (

    select * from {{ ref('fct_tax_collection') }}

),

items as (

    select tax_item_key, tax_group_name from {{ ref('dim_tax_item') }}

)

select
    fact.period_date,
    fact.period_year,
    fact.period_month,
    items.tax_group_name,
    cast(sum(fact.collected_usd) as decimal(18, 2)) as nominal_usd
from fact
inner join items
    on items.tax_item_key = fact.tax_item_key
group by
    fact.period_date,
    fact.period_year,
    fact.period_month,
    items.tax_group_name
