-- Staging: clean operational orders from the Postgres source database.
select
    o.order_id,
    o.customer_id,
    o.order_status,
    o.order_total,
    o.created_at::date as order_date
from public.orders o
where o.order_status <> 'cancelled'
