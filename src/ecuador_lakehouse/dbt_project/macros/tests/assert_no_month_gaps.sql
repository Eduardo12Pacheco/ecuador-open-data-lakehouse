{#
    Fail when the monthly series has a missing month between its own first and
    last observed month, globally or per single-column group.
#}
{% test assert_no_month_gaps(model, date_column, group_by=none, where=none) %}
    with filtered as (
        select
            {%- if group_by %}
            {{ group_by }},
            {%- endif %}
            cast(date_trunc('month', {{ date_column }}) as date) as month_date
        from {{ model }}
        {%- if where %}
        where {{ where }}
        {%- endif %}
    ),
    bounds as (
        select
            {%- if group_by %}
            {{ group_by }},
            {%- endif %}
            min(month_date) as min_month,
            max(month_date) as max_month
        from filtered
        {%- if group_by %}
        group by {{ group_by }}
        {%- endif %}
    ),
    expected as (
        select
            {%- if group_by %}
            {{ group_by }},
            {%- endif %}
            cast(month_date as date) as month_date
        from bounds,
        unnest(
            generate_series(
                cast(min_month as timestamp),
                cast(max_month as timestamp),
                interval 1 month
            )
        ) as months(month_date)
    ),
    actual as (
        select distinct * from filtered
    )
    select expected.*
    from expected
    left join actual
        on actual.month_date = expected.month_date
        {%- if group_by %}
        and actual.{{ group_by }} = expected.{{ group_by }}
        {%- endif %}
    where actual.month_date is null
{% endtest %}
