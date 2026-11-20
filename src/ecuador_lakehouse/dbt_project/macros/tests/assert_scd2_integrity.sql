{#
    Fail when an SCD2 dimension violates any structural invariant.

    Checks: valid ranges, exactly one current version per natural key, no gaps
    or overlaps between consecutive versions (they must be adjacent days) and a
    current flag that agrees with the open-ended ``valid_to``.
#}
{% test assert_scd2_integrity(
    model,
    natural_key,
    valid_from='valid_from',
    valid_to='valid_to',
    is_current='is_current'
) %}
    with versions as (
        select * from {{ model }}
    ),
    ordered as (
        select
            *,
            lag({{ valid_to }}) over (
                partition by {{ natural_key }} order by {{ valid_from }}
            ) as previous_valid_to
        from versions
    ),
    invalid_ranges as (
        select {{ natural_key }}, 'invalid_range' as issue
        from versions
        where {{ valid_from }} > {{ valid_to }}
    ),
    invalid_transitions as (
        select {{ natural_key }}, 'gap_or_overlap' as issue
        from ordered
        where previous_valid_to is not null
          and {{ valid_from }} <> previous_valid_to + interval 1 day
    ),
    invalid_current_counts as (
        select {{ natural_key }}, 'current_count' as issue
        from versions
        group by {{ natural_key }}
        having count(*) filter (where {{ is_current }}) <> 1
    ),
    invalid_current_flags as (
        select {{ natural_key }}, 'current_flag' as issue
        from versions
        where {{ is_current }} <> ({{ valid_to }} = date '9999-12-31')
    )
    select * from invalid_ranges
    union all
    select * from invalid_transitions
    union all
    select * from invalid_current_counts
    union all
    select * from invalid_current_flags
{% endtest %}
