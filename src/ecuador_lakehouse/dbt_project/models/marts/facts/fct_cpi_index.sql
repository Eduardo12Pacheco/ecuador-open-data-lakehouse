with staged as (

    select * from {{ ref('stg_inec__cpi_index') }}

),

items as (

    select * from {{ ref('dim_cpi_item') }}

)

select
    staged.period_date,
    cast(extract(year from staged.period_date) as integer) as period_year,
    cast(extract(month from staged.period_date) as integer) as period_month,
    staged.price_area_key,
    items.cpi_item_key,
    staged.index_value,
    staged.weight,
    staged._batch_id
from staged
inner join items
    on items.ccif_code = staged.ccif_code
