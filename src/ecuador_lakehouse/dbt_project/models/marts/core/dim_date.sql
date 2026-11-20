with bounds as (

    select min(month_start) as min_month, max(month_start) as max_month
    from (
        select min(period_date) as month_start from {{ ref('stg_sri__tax_collection') }}
        union all
        select max(period_date) from {{ ref('stg_sri__tax_collection') }}
        union all
        select min(period_date) from {{ ref('stg_inec__cpi_index') }}
        union all
        select max(period_date) from {{ ref('stg_inec__cpi_index') }}
        union all
        select min(make_date(period_year, (period_quarter - 1) * 3 + 1, 1))
        from {{ ref('stg_bce__national_accounts') }}
        union all
        select max(make_date(period_year, (period_quarter - 1) * 3 + 1, 1))
        from {{ ref('stg_bce__national_accounts') }}
    )

),

months as (

    select cast(month_start as date) as month_start_date
    from bounds,
    unnest(
        generate_series(
            cast(min_month as timestamp),
            cast(max_month as timestamp),
            interval 1 month
        )
    ) as series(month_start)

)

select
    cast(extract(year from month_start_date) * 100 + extract(month from month_start_date) as integer)
        as month_key,
    month_start_date,
    cast(extract(year from month_start_date) as integer) as year,
    cast(extract(quarter from month_start_date) as integer) as quarter,
    cast(extract(month from month_start_date) as integer) as month,
    case extract(month from month_start_date)
        when 1 then 'Enero'
        when 2 then 'Febrero'
        when 3 then 'Marzo'
        when 4 then 'Abril'
        when 5 then 'Mayo'
        when 6 then 'Junio'
        when 7 then 'Julio'
        when 8 then 'Agosto'
        when 9 then 'Septiembre'
        when 10 then 'Octubre'
        when 11 then 'Noviembre'
        when 12 then 'Diciembre'
    end as month_name_es,
    cast(extract(year from month_start_date) as varchar)
        || 'Q'
        || cast(extract(quarter from month_start_date) as varchar) as quarter_key
from months
order by month_start_date
