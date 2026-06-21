-- Staging: captured payments from the Postgres source database.
select
    p.payment_id,
    p.order_id,
    p.amount,
    p.captured_at::date as payment_date
from public.payments p
where p.status = 'captured'
