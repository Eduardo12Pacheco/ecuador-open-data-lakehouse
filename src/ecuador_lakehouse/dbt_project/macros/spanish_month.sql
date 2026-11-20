{#
    Spanish month parsing with a fixed table, never the process locale (D28).

    ``spanish_month`` accepts ``"01 Enero"`` or ``"Enero"`` and returns 1-12.
    ``spanish_month_abbr(..., 'month'|'year')`` parses headers such as
    ``"ene-15"`` (short year 2015) or ``"dic-2024"`` (full year).
#}
{% macro spanish_month(label) -%}
    case upper(trim(regexp_replace(upper(trim({{ label }})), '^[0-9]+', '')))
        when 'ENERO' then 1
        when 'FEBRERO' then 2
        when 'MARZO' then 3
        when 'ABRIL' then 4
        when 'MAYO' then 5
        when 'JUNIO' then 6
        when 'JULIO' then 7
        when 'AGOSTO' then 8
        when 'SEPTIEMBRE' then 9
        when 'OCTUBRE' then 10
        when 'NOVIEMBRE' then 11
        when 'DICIEMBRE' then 12
    end
{%- endmacro %}

{% macro spanish_month_abbr(label, part='month') -%}
    {%- if part == 'year' -%}
        case
            when length(trim(split_part({{ label }}, '-', 2))) = 2
                then 2000 + cast(trim(split_part({{ label }}, '-', 2)) as integer)
            else cast(trim(split_part({{ label }}, '-', 2)) as integer)
        end
    {%- else -%}
        case lower(trim(split_part({{ label }}, '-', 1)))
            when 'ene' then 1
            when 'feb' then 2
            when 'mar' then 3
            when 'abr' then 4
            when 'may' then 5
            when 'jun' then 6
            when 'jul' then 7
            when 'ago' then 8
            when 'sep' then 9
            when 'oct' then 10
            when 'nov' then 11
            when 'dic' then 12
        end
    {%- endif -%}
{%- endmacro %}
