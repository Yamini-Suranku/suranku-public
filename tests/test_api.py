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
    res = client.post("/api/chat", json={"question": "How does lineage work?"})
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "deterministic"
    assert "lineage" in body["answer"].lower()


def test_static_frontend_is_served_at_root():
    res = client.get("/")
    assert res.status_code == 200
    assert "Suranku" in res.text


def test_safe_path_rejects_traversal():
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        main.safe_path(main.DEMO_DIR, "../../etc/passwd")
