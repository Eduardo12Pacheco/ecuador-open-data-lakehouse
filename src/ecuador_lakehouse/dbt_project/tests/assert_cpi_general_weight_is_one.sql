-- The general CPI item carries the whole area weight (1.0).
select
    fact.price_area_key,
    fact.period_date,
    fact.weight
from {{ ref('fct_cpi_index') }} as fact
inner join {{ ref('dim_cpi_item') }} as items
    on items.cpi_item_key = fact.cpi_item_key
where items.level = 'general'
  and abs(fact.weight - 1.0) > 1e-9
