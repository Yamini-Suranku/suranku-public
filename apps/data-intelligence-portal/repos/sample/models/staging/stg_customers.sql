-- Staging: customers from the Postgres source database.
select
    c.customer_id,
    c.full_name,
    c.email,
    c.region_id
from public.customers c
