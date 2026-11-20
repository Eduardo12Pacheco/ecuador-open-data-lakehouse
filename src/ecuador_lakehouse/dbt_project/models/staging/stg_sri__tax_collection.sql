with source as (

    select * from {{ source('raw', 'sri_tax_collection') }}

),

typed as (

    select
        cast(trim(anio) as integer) as period_year,
        {{ spanish_month('mes_label') }} as period_month,
        {{ norm_key('grupo') }} as tax_group_key,
        trim(grupo) as tax_group_name,
        {{ norm_key('subgrupo') }} as tax_subgroup_key,
        trim(subgrupo) as tax_subgroup_name,
        {{ norm_key('impuesto') }} as tax_key,
        trim(impuesto) as tax_name,
        {{ norm_key('tipo_contribuyente') }} as taxpayer_type,
        {{ norm_key('provincia') }} as province_key,
        coalesce(nullif(trim(canton), ''), 'NO DESAGREGADO') as canton_name,
        {{ norm_key("nullif(trim(canton), '')") }} as canton_key,
        cast(replace(trim(valor_raw), ',', '.') as decimal(18, 2)) as collected_usd,
        _batch_id,
        _source_file
    from source

),

with_period_date as (

    select
        *,
        make_date(period_year, period_month, 1) as period_date
    from typed

)

select
    period_year,
    period_month,
    period_date,
    tax_group_key,
    tax_group_name,
    tax_subgroup_key,
    tax_subgroup_name,
    tax_key,
    tax_name,
    taxpayer_type,
    province_key,
    canton_name,
    canton_key,
    cast(sum(collected_usd) as decimal(18, 2)) as collected_usd,
    _batch_id,
    _source_file
from with_period_date
group by all
