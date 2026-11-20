with items as (

    select distinct
        ccif_code,
        level,
        ccif_parent_code,
        ccif_name
    from {{ ref('stg_inec__cpi_index') }}

)

select
    {{ surrogate_key(['items.ccif_code']) }} as cpi_item_key,
    items.ccif_code,
    items.level,
    items.ccif_parent_code,
    items.ccif_name
from items
order by items.ccif_code
