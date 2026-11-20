with items as (

    select
        account_code,
        any_value(account_name) as account_name
    from {{ ref('stg_bce__national_accounts') }}
    where account_code like 'I___'
       or account_code in ('IVAB1', 'IVAB2', 'IVAB3', 'PGCFH1', 'PGCFGC1', 'PFBCF1', 'PEBS2', 'PIBS2')
    group by account_code

)

select
    {{ surrogate_key(['items.account_code']) }} as account_item_key,
    items.account_code,
    items.account_name as item_name,
    case items.account_code
        when 'IVAB1' then 'vab_total'
        when 'IVAB2' then 'other_gdp_elements'
        when 'IVAB3' then 'gdp_total'
        when 'PGCFH1' then 'household_consumption'
        when 'PGCFGC1' then 'government_consumption'
        when 'PFBCF1' then 'gross_fixed_capital'
        when 'PEBS2' then 'exports'
        when 'PIBS2' then 'imports'
        else 'industry'
    end as kind
from items
order by items.account_code
