"""Unit tests for the SQL parser (sqlglot-backed)."""
from backend.app.scanner.sql_parser import parse_sql


def test_cte_and_nested_subquery_column_lineage():
    sql = """
    with recent as (
        select o.order_id, o.amount, o.customer_id
        from raw.orders o where o.status = 'paid'
    )
    select r.customer_id, sum(r.amount) as total_spend
    from recent r
    join (select customer_id, region from raw.customers) c on c.customer_id = r.customer_id
    group by r.customer_id
    """
    res = parse_sql(sql, default_target="analytics.customer_spend")

    # CTE excluded; real source tables resolved through the CTE
    assert set(res["source_tables"]) == {"raw.orders", "raw.customers"}
    assert "recent" not in res["source_tables"]

    # table edges point at the target
    targets = {e["target"] for e in res["table_edges"]}
    assert targets == {"analytics.customer_spend"}

    # column lineage traces through the CTE back to raw.orders with the transformation
    spend = next(c for c in res["column_edges"] if c["target_column"] == "total_spend")
    assert spend["source_table"] == "raw.orders"
    assert spend["source_column"] == "amount"
    assert "SUM" in (spend["transformation"] or "").upper()
    assert not res["warnings"]


def test_create_table_as_uses_ddl_target():
    res = parse_sql("create table mart.daily as select d.id, count(*) c from raw.deals d group by d.id")
    assert res["targets"] == ["mart.daily"]
    assert {"source": "raw.deals", "target": "mart.daily", "relation": "derived_from"} in res["table_edges"]


def test_select_star_falls_back_to_table_level():
    res = parse_sql("select * from raw.orders", default_target="stg.orders")
    assert "raw.orders" in res["source_tables"]
    # no column lineage for * without a schema, but it must not error
    assert res["warnings"] == []


def test_bad_sql_is_a_warning_not_a_raise():
    res = parse_sql("select from where group by", default_target="x")
    assert res["warnings"]  # reported, not raised


def test_dbt_jinja_is_rendered():
    sql = """
    {{ config(materialized='table') }}
    with src as (select * from {{ source('raw', 'orders') }})
    select o.id, o.amount from {{ ref('stg_orders') }} o
    """
    res = parse_sql(sql, default_target="fct_orders")
    assert "raw.orders" in res["source_tables"]
    assert "stg_orders" in res["source_tables"]
    assert not res["warnings"]  # Jinja resolved, parses cleanly
