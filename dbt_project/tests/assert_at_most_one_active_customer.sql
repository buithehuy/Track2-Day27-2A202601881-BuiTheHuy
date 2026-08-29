-- An active SCD dimension must contribute at most one row per customer.
select customer_id
from {{ ref('stg_customers') }}
where is_active = true
group by customer_id
having count(*) > 1

