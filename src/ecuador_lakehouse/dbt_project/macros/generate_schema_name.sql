{#
    Use ``+schema: staging|intermediate|marts`` verbatim instead of dbt's
    default ``<target_schema>_<custom_schema>`` concatenation (S7, D3).
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
