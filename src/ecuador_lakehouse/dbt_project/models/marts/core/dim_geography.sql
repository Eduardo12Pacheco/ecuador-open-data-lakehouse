with geographies as (

    select
        province_key,
        coalesce(canton_key, 'NO DESAGREGADO') as canton_key,
        any_value(canton_name) as canton_name
    from {{ ref('stg_sri__tax_collection') }}
    group by province_key, coalesce(canton_key, 'NO DESAGREGADO')

)

select
    {{ surrogate_key(['geographies.province_key', 'geographies.canton_key']) }} as geography_key,
    geographies.province_key,
    provinces.province_name,
    geographies.canton_key,
    geographies.canton_name
from geographies
inner join {{ ref('ref_province') }} as provinces
    on provinces.province_key = geographies.province_key
order by geographies.province_key, geographies.canton_key
