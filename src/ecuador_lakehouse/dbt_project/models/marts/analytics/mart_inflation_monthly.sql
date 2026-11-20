with cpi as (

    select
        fact.period_date,
        fact.period_year,
        fact.period_month,
        fact.price_area_key,
        areas.price_area_name,
        fact.cpi_item_key,
        items.ccif_code,
        items.ccif_name,
        items.level,
        fact.index_value
    from {{ ref('fct_cpi_index') }} as fact
    inner join {{ ref('dim_cpi_item') }} as items
        on items.cpi_item_key = fact.cpi_item_key
    inner join {{ ref('dim_price_area') }} as areas
        on areas.price_area_key = fact.price_area_key
    where items.level in ('general', 'division')

),

lagged as (

    select
        cpi.*,
        lag(cpi.index_value) over (
            partition by cpi.price_area_key, cpi.cpi_item_key
            order by cpi.period_date
        ) as previous_month_index,
        lag(cpi.index_value, 12) over (
            partition by cpi.price_area_key, cpi.cpi_item_key
            order by cpi.period_date
        ) as previous_year_index
    from cpi

)

select
    period_date,
    period_year,
    period_month,
    price_area_key,
    price_area_name,
    cpi_item_key,
    ccif_code,
    ccif_name,
    level,
    index_value,
    case
        when previous_month_index is null or previous_month_index = 0 then null
        else cast(index_value / previous_month_index - 1 as double)
    end as mom,
    case
        when previous_year_index is null or previous_year_index = 0 then null
        else cast(index_value / previous_year_index - 1 as double)
    end as yoy
from lagged
order by price_area_key, cpi_item_key, period_date
