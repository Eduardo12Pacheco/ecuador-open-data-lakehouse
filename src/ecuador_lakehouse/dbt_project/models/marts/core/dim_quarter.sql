with quarters as (

    select distinct period_year, period_quarter
    from {{ ref('stg_bce__national_accounts') }}

)

select
    cast(period_year as varchar) || 'Q' || cast(period_quarter as varchar) as quarter_key,
    cast(period_year as integer) as year,
    cast(period_quarter as integer) as quarter,
    make_date(period_year, (period_quarter - 1) * 3 + 1, 1) as quarter_start_date,
    last_day(make_date(period_year, period_quarter * 3, 1)) as quarter_end_date
from quarters
order by period_year, period_quarter
