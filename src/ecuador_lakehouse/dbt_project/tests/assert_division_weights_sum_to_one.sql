-- The twelve CCIF divisions of every price area must sum to the total weight.
select
    fact.price_area_key,
    fact.period_date,
    sum(fact.weight) as division_weight_sum
from {{ ref('fct_cpi_index') }} as fact
inner join {{ ref('dim_cpi_item') }} as items
    on items.cpi_item_key = fact.cpi_item_key
where items.level = 'division'
group by fact.price_area_key, fact.period_date
having abs(sum(fact.weight) - 1.0) > 0.001
