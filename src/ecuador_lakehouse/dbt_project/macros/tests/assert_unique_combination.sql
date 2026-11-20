{#
    Fail when the same combination of columns appears more than once.
#}
{% test assert_unique_combination(model, combination_of_columns, where=none) %}
    {%- set columns = combination_of_columns | join(', ') %}
    select {{ columns }}, count(*) as row_count
    from {{ model }}
    {%- if where %}
    where {{ where }}
    {%- endif %}
    group by {{ columns }}
    having count(*) > 1
{% endtest %}
