{{ config(
    materialized='incremental',
    incremental_strategy='delete+insert',
    unique_key='period_year',
    on_schema_change='fail'
) }}

with staged as (

    select * from {{ ref('stg_sri__tax_collection') }}
    {% if is_incremental() %}
    where _batch_id not in (select distinct _batch_id from {{ this }})
    {% endif %}

),

tax_items as (

    select * from {{ ref('dim_tax_item') }}
    where lifecycle_status = 'active'

),

geographies as (

    select * from {{ ref('dim_geography') }}

)

select
    staged.period_year,
    staged.period_month,
    staged.period_date,
    tax_items.tax_item_key,
    tax_items.tax_item_nk,
    staged.taxpayer_type,
    geographies.geography_key,
    cast(sum(staged.collected_usd) as decimal(18, 2)) as collected_usd,
    any_value(staged._batch_id) as _batch_id
from staged
inner join tax_items
    on tax_items.tax_item_nk = staged.tax_key || '|' || staged.tax_subgroup_key
    and staged.period_year between extract(year from tax_items.valid_from)
        and extract(year from tax_items.valid_to)
inner join geographies
    on geographies.province_key = staged.province_key
    and geographies.canton_key = coalesce(staged.canton_key, 'NO DESAGREGADO')
group by
    staged.period_year,
    staged.period_month,
    staged.period_date,
    tax_items.tax_item_key,
    tax_items.tax_item_nk,
    staged.taxpayer_type,
    geographies.geography_key
