with presence as (

    select * from {{ ref('int_tax_item_year_presence') }}

),

max_year as (

    select max(period_year) as max_loaded_year from presence

),

first_presence as (

    select tax_item_nk, min(period_year) as first_year
    from presence
    where present
    group by tax_item_nk

),

spine as (

    select
        first_presence.tax_item_nk,
        years.period_year
    from first_presence
    cross join max_year
    cross join lateral (
        select unnest(
            generate_series(first_presence.first_year, max_year.max_loaded_year)
        ) as period_year
    ) as years

),

filled as (

    select
        spine.tax_item_nk,
        spine.period_year,
        case when presence.present then 'active' else 'inactive' end as lifecycle_status,
        presence.tax_group_name as observed_group_name
    from spine
    left join presence
        on presence.tax_item_nk = spine.tax_item_nk
        and presence.period_year = spine.period_year

),

carried as (

    select
        *,
        last_value(observed_group_name ignore nulls) over (
            partition by tax_item_nk order by period_year
            rows between unbounded preceding and current row
        ) as tax_group_name
    from filled

),

flagged as (

    select
        *,
        case
            when lag(lifecycle_status) over w is distinct from lifecycle_status then 1
            when lag(tax_group_name) over w is distinct from tax_group_name then 1
            else 0
        end as changed
    from carried
    window w as (partition by tax_item_nk order by period_year)

),

islands as (

    select
        *,
        sum(changed) over (
            partition by tax_item_nk order by period_year
            rows between unbounded preceding and current row
        ) as island_id
    from flagged

),

versions as (

    select
        tax_item_nk,
        island_id,
        any_value(lifecycle_status) as lifecycle_status,
        any_value(tax_group_name) as tax_group_name,
        min(period_year) as start_year,
        max(period_year) as end_year
    from islands
    group by tax_item_nk, island_id

)

select
    versions.tax_item_nk,
    versions.tax_group_name,
    versions.lifecycle_status,
    make_date(versions.start_year, 1, 1) as valid_from,
    case
        when versions.end_year = max_year.max_loaded_year then date '9999-12-31'
        else make_date(versions.end_year, 12, 31)
    end as valid_to
from versions
cross join max_year
order by versions.tax_item_nk, valid_from
