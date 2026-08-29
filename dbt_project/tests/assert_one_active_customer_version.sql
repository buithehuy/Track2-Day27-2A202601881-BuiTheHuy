select customer_id
from {{ ref('stg_customers') }}
where is_active = true
group by customer_id
having count(*) > 1
