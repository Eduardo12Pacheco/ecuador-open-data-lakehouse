-- No source may publish a period beyond the build date (no fabricated future).
select 'sri_tax' as source_id, period_date
from {{ ref('fct_tax_collection') }}
where period_date > current_date

union all

select 'inec_cpi' as source_id, period_date
from {{ ref('fct_cpi_index') }}
where period_date > current_date

union all

select 'bce_cnt' as source_id,
       make_date(period_year, (period_quarter - 1) * 3 + 1, 1) as period_date
from {{ ref('fct_national_accounts') }}
where make_date(period_year, (period_quarter - 1) * 3 + 1, 1) > current_date
