-- Order fact: orders with their captured payment totals and balance due.
create table analytics.fct_orders as
with paid as (
    select order_id, sum(amount) as paid_amount
    from stg_payments
    group by order_id
)
select
    o.order_id,
    o.customer_id,
    o.order_date,
    o.order_total,
    coalesce(p.paid_amount, 0) as paid_amount,
    (o.order_total - coalesce(p.paid_amount, 0)) as balance_due
from stg_orders o
left join paid p on p.order_id = o.order_id
