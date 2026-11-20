{#
    Deterministic surrogate key (D11): md5 over the natural-key parts joined by
    ``||``. Never ``row_number()``, so two builds of the same data agree.
#}
{% macro surrogate_key(field_list) -%}
    md5(
        concat_ws(
            '||',
            {% for field in field_list -%}
            cast({{ field }} as varchar){% if not loop.last %}, {% endif %}
            {%- endfor %}
        )
    )
{%- endmacro %}
