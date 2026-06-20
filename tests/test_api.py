"""HTTP-level tests exercising the FastAPI app end to end via TestClient."""
from fastapi.testclient import TestClient

from backend.app import main


client = TestClient(main.app)


def test_health_endpoint():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_demo_reset_then_ingestion_over_http():
    assert client.post("/api/demo/reset").status_code == 200

    res = client.post("/api/ingestion-runs/demo")
    assert res.status_code == 200
    assert res.json()["marker_id"] == "commerce-batch-001"
    assert len(res.json()["runs"]) == 3

    assert len(client.get("/api/contracts").json()) == 3
    assert len(client.get("/api/catalogs").json()) == 9
    assert len(client.get("/api/lineage/data").json()) == 9
    assert len(client.get("/api/lineage/process").json()) == 9


def test_ingestion_is_idempotent_on_catalogs():
    client.post("/api/demo/reset")
    client.post("/api/ingestion-runs/demo")
    client.post("/api/ingestion-runs/demo")
    # catalog_tables are upserted by layer.domain.event, so the count is stable
    assert len(client.get("/api/catalogs").json()) == 9


def test_contracts_include_schema_text():
    client.post("/api/demo/reset")
    contracts = client.get("/api/contracts").json()
    assert all("proto3" in c["schema"] for c in contracts)


def test_chat_requires_a_question():
    res = client.post("/api/chat", json={"question": "   "})
    assert res.status_code == 400


def test_chat_falls_back_to_deterministic_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    res = client.post("/api/chat", json={"question": "How does lineage work?"})
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "deterministic"
    assert "lineage" in body["answer"].lower()


def test_anthropic_answer_is_skipped_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main.anthropic_answer("How does lineage work?") is None


def test_static_frontend_is_served_at_root():
    res = client.get("/")
    assert res.status_code == 200
    assert "Suranku" in res.text


def test_safe_path_rejects_traversal():
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        main.safe_path(main.DEMO_DIR, "../../etc/passwd")


# --------------------------------------------------------- authoring + monitoring

def test_authoring_flow_create_contract_events_and_ingest():
    client.post("/api/demo/reset")
    domain = client.post("/api/domains", json={"name": "Payments Ops", "owner": "Finance", "description": "x"})
    assert domain.status_code == 201
    domain_id = domain.json()["id"]

    contract = client.post("/api/contracts", json={
        "domain_id": domain_id, "topic": "pay.tx.created", "event_name": "tx_created",
        "version": "v1", "primary_keys": ["tx_id"], "schema_text": 'syntax = "proto3";',
        "description": "tx",
    })
    assert contract.status_code == 201
    contract_id = contract.json()["id"]

    events = client.post("/api/events", json={"contract_id": contract_id, "records": [
        {"tx_id": "t1", "amount": 10}, {"tx_id": "t1", "amount": 10}, {"tx_id": "t2", "amount": 5},
    ]})
    assert events.status_code == 201 and events.json()["added"] == 3

    run = client.post("/api/ingestion-runs")
    assert run.status_code == 200
    assert any(r["contract_id"] == contract_id and r["records_deduped"] == 1 for r in run.json()["runs"])

    catalogs = client.get("/api/catalogs").json()
    assert any(t["source_contract_id"] == contract_id for t in catalogs)

    contracts = client.get("/api/contracts").json()
    assert any(c["id"] == contract_id and "proto3" in c["schema"] for c in contracts)


def test_contract_requires_primary_keys():
    res = client.post("/api/contracts", json={
        "domain_id": "d", "topic": "t", "event_name": "e", "version": "v1", "primary_keys": []})
    assert res.status_code == 400


def test_events_for_unknown_contract_404():
    assert client.post("/api/events", json={"contract_id": "nope", "records": [{"a": 1}]}).status_code == 404


def test_generalized_ingestion_without_events_is_400():
    client.post("/api/demo/reset")  # demo contracts have no stored events
    assert client.post("/api/ingestion-runs").status_code == 400


def test_manual_lineage_posts_appear_in_listing():
    client.post("/api/demo/reset")
    assert client.post("/api/lineage/data", json={"source": "a", "target": "b", "relation": "derived_from"}).status_code == 201
    assert client.post("/api/lineage/process", json={"marker_id": "m", "run_id": "r", "step_name": "s", "detail": "d"}).status_code == 201
    assert any(e["source"] == "a" for e in client.get("/api/lineage/data").json())
    assert any(e["step_name"] == "s" for e in client.get("/api/lineage/process").json())


def test_readiness_reports_dependencies():
    res = client.get("/api/readiness")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in {"ready", "degraded"}
    names = {c["name"] for c in body["checks"]}
    assert {"database", "object_store", "ai_provider", "seed_data"} <= names
    database = next(c for c in body["checks"] if c["name"] == "database")
    assert database["status"] == "ok" and "latency_ms" in database


def test_agents_endpoint_returns_list():
    res = client.get("/api/agents")
    assert res.status_code == 200
    assert isinstance(res.json(), list)
