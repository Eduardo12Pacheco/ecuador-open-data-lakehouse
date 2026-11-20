with monthly as (

    select * from {{ ref('int_tax_collection_monthly') }}

),

cpi as (

    select * from {{ ref('int_cpi_national_monthly') }}

),

deflated as (

    select
        monthly.period_date,
        monthly.period_year,
        monthly.period_month,
        monthly.tax_group_name,
        monthly.nominal_usd,
        cpi.index_value,
        case
            when cpi.index_value is null or cpi.index_value = 0 then null
            else cast(monthly.nominal_usd / (cpi.index_value / 100.0) as decimal(18, 2))
        end as real_usd_2014
    from monthly
    left join cpi
        on cpi.period_date = monthly.period_date

),

with_prior as (

    select
        deflated.*,
        prior.nominal_usd as prior_year_nominal,
        sum(deflated.nominal_usd) over (partition by deflated.period_date) as month_total
    from deflated
    left join monthly as prior
        on prior.tax_group_name = deflated.tax_group_name
        and prior.period_year = deflated.period_year - 1
        and prior.period_month = deflated.period_month

)

select
    period_date,
    period_year,
    period_month,
    {{ norm_key('tax_group_name') }} as tax_group_key,
    tax_group_name,
    nominal_usd,
    real_usd_2014,
    case
        when prior_year_nominal is null or prior_year_nominal = 0 then null
        else cast((nominal_usd - prior_year_nominal) / prior_year_nominal as double)
    end as yoy_nominal,
    cast(nominal_usd / month_total as double) as share_of_month
from with_prior
order by period_date, tax_group_name
