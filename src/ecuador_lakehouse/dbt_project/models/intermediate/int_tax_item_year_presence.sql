with observed as (

    select
        tax_key || '|' || tax_subgroup_key as tax_item_nk,
        period_year,
        any_value(tax_group_name) as tax_group_name
    from {{ ref('stg_sri__tax_collection') }}
    group by tax_item_nk, period_year

),

loaded_years as (

    select distinct period_year
    from {{ ref('stg_sri__tax_collection') }}

),

tax_items as (

    select distinct tax_item_nk from observed

),

spine as (

    select tax_items.tax_item_nk, loaded_years.period_year
    from tax_items
    cross join loaded_years

)

select
    spine.tax_item_nk,
    spine.period_year,
    observed.tax_item_nk is not null as present,
    observed.tax_group_name
from spine
left join observed
    on observed.tax_item_nk = spine.tax_item_nk
    and observed.period_year = spine.period_year
