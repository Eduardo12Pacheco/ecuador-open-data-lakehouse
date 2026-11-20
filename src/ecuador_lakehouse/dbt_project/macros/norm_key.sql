{#
    Normalize a human label exactly like Python ``domain.text.normalize_key`` (D12).

    Uppercase, translate the accented uppercase letters to their unaccented
    counterparts, collapse runs of non ``[A-Z0-9]`` characters to one space and
    trim. The explicit mapping avoids ICU/NFKD differences between Python and
    DuckDB, which a differential test enforces.
#}
{% macro norm_key(label) -%}
    trim(
        regexp_replace(
            translate(
                upper(trim({{ label }})),
                'ÁÀÂÄÃÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÑÇ',
                'AAAAAEEEEIIIIOOOOOUUUUNC'
            ),
            '[^A-Z0-9]+',
            ' ',
            'g'
        )
    )
{%- endmacro %}
