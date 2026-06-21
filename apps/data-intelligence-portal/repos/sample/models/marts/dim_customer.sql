-- Customer dimension: staged customers enriched with region reference data.
create table analytics.dim_customer as
select
    c.customer_id,
    c.full_name,
    c.email,
    r.region_name
from stg_customers c
left join public.regions r on r.region_id = c.region_id
