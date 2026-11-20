with versions as (

    select * from {{ ref('int_tax_item_versions') }}

),

latest_names as (

    select
        tax_key || '|' || tax_subgroup_key as tax_item_nk,
        arg_max(tax_subgroup_name, period_year) as tax_subgroup_name,
        arg_max(tax_name, period_year) as tax_name
    from {{ ref('stg_sri__tax_collection') }}
    group by tax_item_nk

)

select
    {{ surrogate_key(['versions.tax_item_nk', 'versions.valid_from']) }} as tax_item_key,
    versions.tax_item_nk,
    versions.tax_group_name,
    latest_names.tax_subgroup_name,
    latest_names.tax_name,
    versions.lifecycle_status,
    versions.valid_from,
    versions.valid_to,
    versions.valid_to = date '9999-12-31' as is_current
from versions
inner join latest_names using (tax_item_nk)
order by versions.tax_item_nk, versions.valid_from
