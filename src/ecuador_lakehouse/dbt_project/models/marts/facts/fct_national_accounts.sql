with staged as (

    select * from {{ ref('stg_bce__national_accounts') }}

),

items as (

    select * from {{ ref('dim_national_account_item') }}

)

select
    staged.period_year,
    staged.period_quarter,
    cast(staged.period_year as varchar)
        || 'Q'
        || cast(staged.period_quarter as varchar) as quarter_key,
    items.account_item_key,
    staged.price_basis,
    staged.value_thousand_usd
from staged
inner join items
    on items.account_code = staged.account_code
where staged.value_thousand_usd is not null
