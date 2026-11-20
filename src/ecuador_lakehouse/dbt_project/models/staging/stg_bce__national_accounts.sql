with source as (

    select * from {{ source('raw', 'bce_cnt_quarterly') }}

),

typed as (

    select
        trim(tipo_variable) as variable_type,
        trim(variable) as variable,
        trim(codigo) as account_code,
        trim(descripcion) as account_name,
        trim(unidades) as unit,
        cast(trim(anio) as integer) as period_year,
        cast(trim(trimestre) as integer) as period_quarter,
        case
            when upper(tipo_variable) like '%CONSTANTE%' then 'constant_2007'
            when upper(tipo_variable) like '%CORRIENTE%' then 'current'
        end as price_basis,
        case
            when nullif(trim(valor_raw), '') is null then null
            else try_cast(replace(trim(valor_raw), ',', '') as bigint)
        end as value_thousand_usd,
        _batch_id,
        _source_file
    from source

)

select * from typed
