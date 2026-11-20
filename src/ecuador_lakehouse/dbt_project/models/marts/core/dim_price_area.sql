select
    price_area_key,
    price_area_name,
    area_kind
from {{ ref('ref_price_area') }}
order by price_area_key
