-- NOTE: This model is intentionally simple. If the customer dimension has more
-- than one active row per customer, the join can inflate revenue without a SQL
-- error. Students should add tests/unit tests that expose this failure mode.

with completed_orders as (
    select *
    from {{ ref('stg_orders') }}
    where status = 'completed'
),
active_customers as (
    -- A customer can have SCD history. Keep one active version so the join
    -- cannot duplicate an order and inflate the aggregate.
    select customer_id
    from (
        select
            customer_id,
            row_number() over (
                partition by customer_id
                order by valid_from desc nulls last
            ) as active_rank
        from {{ ref('stg_customers') }}
        where is_active = true
    )
    where active_rank = 1
)
select
    o.order_date,
    count(*) as completed_order_rows,
    sum(o.amount_usd) as daily_revenue
from completed_orders o
left join active_customers c
    on o.customer_id = c.customer_id
group by 1
order by 1
