with presence as (

    select
        tax_item_nk,
        cast(min(period_year) filter (where present) as integer) as first_year,
        cast(max(period_year) filter (where present) as integer) as last_year,
        cast(count(*) filter (where present) as integer) as years_active
    from {{ ref('int_tax_item_year_presence') }}
    group by tax_item_nk

),

versions as (

    select
        tax_item_nk,
        cast(count(*) as integer) as versions_count,
        max(case when is_current then lifecycle_status end) as current_status,
        arg_max(tax_name, valid_from) as tax_name,
        arg_max(tax_group_name, valid_from) as tax_group_name
    from {{ ref('dim_tax_item') }}
    group by tax_item_nk

),

collected as (

    select
        tax_item_nk,
        cast(sum(collected_usd) as decimal(18, 2)) as total_collected_usd
    from {{ ref('fct_tax_collection') }}
    group by tax_item_nk

)

select
    presence.tax_item_nk,
    versions.tax_name,
    versions.tax_group_name,
    presence.first_year,
    presence.last_year,
    presence.years_active,
    versions.versions_count,
    coalesce(collected.total_collected_usd, cast(0 as decimal(18, 2))) as total_collected_usd,
    versions.current_status
from presence
inner join versions
    on versions.tax_item_nk = presence.tax_item_nk
left join collected
    on collected.tax_item_nk = presence.tax_item_nk
order by presence.tax_item_nk
