{#
    Fail when a column falls outside an inclusive numeric/date range.
    Either bound may be omitted; an optional ``where`` narrows the rows.
#}
{% test assert_between(model, column_name, min_value=none, max_value=none, where=none) %}
    {%- if min_value is none and max_value is none -%}
        {{ exceptions.raise_compiler_error("assert_between needs min_value or max_value") }}
    {%- endif -%}
    select *
    from {{ model }}
    where
    {%- if where %}
        ({{ where }}) and
    {%- endif %}
    {%- if min_value is not none %}
        {{ column_name }} < {{ min_value }}
    {%- endif %}
    {%- if min_value is not none and max_value is not none %} or {% endif -%}
    {%- if max_value is not none %}
        {{ column_name }} > {{ max_value }}
    {%- endif %}
{% endtest %}
