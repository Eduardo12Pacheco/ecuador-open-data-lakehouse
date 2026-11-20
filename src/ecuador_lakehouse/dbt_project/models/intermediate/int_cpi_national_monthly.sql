with cpi as (

    select
        fact.period_date,
        fact.period_year,
        fact.period_month,
        fact.index_value,
        fact.weight
    from {{ ref('fct_cpi_index') }} as fact
    inner join {{ ref('dim_cpi_item') }} as items
        on items.cpi_item_key = fact.cpi_item_key
    inner join {{ ref('dim_price_area') }} as areas
        on areas.price_area_key = fact.price_area_key
    where areas.price_area_key = 'NACIONAL'
      and items.level = 'general'

)

select
    period_date,
    period_year,
    period_month,
    index_value,
    weight
from cpi
order by period_date
