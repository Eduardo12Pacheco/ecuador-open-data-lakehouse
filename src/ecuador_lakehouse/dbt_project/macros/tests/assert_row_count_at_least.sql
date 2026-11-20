{#
    Fail when a model (optionally per group) has fewer than ``min_rows`` rows.
#}
{% test assert_row_count_at_least(model, min_rows, group_by=none, where=none) %}
    {%- if group_by is none %}
    select count(*) as row_count
    from {{ model }}
    {%- if where %}
    where {{ where }}
    {%- endif %}
    having count(*) < {{ min_rows }}
    {%- else %}
    select {{ group_by }}, count(*) as row_count
    from {{ model }}
    {%- if where %}
    where {{ where }}
    {%- endif %}
    group by {{ group_by }}
    having count(*) < {{ min_rows }}
    {%- endif %}
{% endtest %}
