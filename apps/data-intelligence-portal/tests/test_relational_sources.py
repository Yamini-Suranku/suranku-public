"""Relational (non-Kafka) sources and the one-click sample-repo scan."""
from fastapi.testclient import TestClient

from backend.app import main

client = TestClient(main.app)


def test_relational_source_needs_no_primary_keys_or_kafka():
    client.post("/api/demo/reset")
    res = client.post("/api/contracts", json={
        "domain_id": "warehouse",
        "source_type": "relational",
        "topic": "public.orders",   # a table, not a Kafka topic
        "event_name": "orders",
    })
    assert res.status_code == 201
    assert res.json()["source_type"] == "relational"
    contracts = client.get("/api/contracts").json()
    assert any(c["id"] == res.json()["id"] and c.get("source_type") == "relational" for c in contracts)


def test_relational_source_requires_a_table():
    res = client.post("/api/contracts", json={
        "domain_id": "d", "source_type": "relational", "event_name": "e", "topic": ""})
    assert res.status_code == 400


def test_kafka_source_still_requires_primary_keys():
    # No source_type -> defaults to kafka -> primary keys required (unchanged behavior).
    res = client.post("/api/contracts", json={
        "domain_id": "d", "topic": "t", "event_name": "e", "primary_keys": []})
    assert res.status_code == 400


def test_scan_demo_builds_sample_lineage():
    client.post("/api/demo/reset")
    res = client.post("/api/scan/demo")
    assert res.status_code == 200
    summary = res.json()
    assert summary["files"] >= 6  # 6 SQL + Tableau + PowerBI

    edges = {(e["source"], e["target"]) for e in client.get("/api/lineage/data").json()}
    # source -> staging -> marts -> report, across files
    assert ("public.orders", "stg_orders") in edges
    assert ("stg_orders", "analytics.fct_orders") in edges
    assert ("analytics.fct_orders", "analytics.mart_revenue") in edges
    assert ("analytics.mart_revenue", "sales_overview") in edges  # Tableau report

    # column lineage with a transformation on the revenue mart
    cols = client.get("/api/lineage/columns", params={"table": "analytics.mart_revenue"}).json()
    assert any("SUM" in (c["transformation"] or "").upper() for c in cols)


def test_rescanning_is_idempotent():
    client.post("/api/demo/reset")
    client.post("/api/scan/demo")
    first = len(client.get("/api/lineage/columns", params={"table": "analytics.mart_revenue"}).json())
    client.post("/api/scan/demo")  # re-scan the same source
    second = len(client.get("/api/lineage/columns", params={"table": "analytics.mart_revenue"}).json())
    assert first == second  # edges replaced, not accumulated
