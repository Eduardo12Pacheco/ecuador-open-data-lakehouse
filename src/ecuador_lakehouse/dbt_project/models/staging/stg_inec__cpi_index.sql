with source as (

    select * from {{ source('raw', 'inec_cpi_index') }}

),

typed as (

    select
        {{ norm_key('price_area') }} as price_area_key,
        case upper(trim(nivel))
            when 'GENERAL' then 'general'
            when 'DIVISIÓN' then 'division'
            when 'DIVISION' then 'division'
            when 'GRUPO' then 'group'
            when 'CLASE' then 'class'
            when 'SUBCLASE' then 'subclass'
            when 'PRODUCTO' then 'product'
        end as level,
        case
            when position(',' in ponderacion_raw) > 0
                then try_cast(replace(trim(ponderacion_raw), ',', '.') as double)
            else try_cast(trim(ponderacion_raw) as double)
        end as weight,
        trim(codigo_ccif) as ccif_code,
        trim(descripcion) as ccif_name,
        make_date(
            {{ spanish_month_abbr('month_label', 'year') }},
            {{ spanish_month_abbr('month_label', 'month') }},
            1
        ) as period_date,
        try_cast(trim(value_raw) as double) as index_value,
        _batch_id,
        _source_file
    from source

),

with_parent as (

    select
        *,
        case level
            when 'general' then null
            when 'division' then '0'
            when 'group' then left(ccif_code, 2)
            when 'class' then left(ccif_code, 3)
            when 'subclass' then left(ccif_code, 4)
            when 'product' then left(ccif_code, 5)
        end as ccif_parent_code
    from typed

)

select * from with_parent
