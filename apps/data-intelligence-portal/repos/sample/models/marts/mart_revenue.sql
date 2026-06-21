-- Revenue mart: paid revenue and order counts by customer region.
create table analytics.mart_revenue as
select
    d.region_name,
    count(distinct f.order_id) as order_count,
    sum(f.paid_amount)         as revenue
from analytics.fct_orders f
join analytics.dim_customer d on d.customer_id = f.customer_id
group by d.region_name
