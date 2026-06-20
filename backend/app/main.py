from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


ROOT = Path(os.getenv("PORTAL_HOME", Path(__file__).resolve().parents[2]))
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("PORTAL_DB", DATA_DIR / "portal.db"))
OBJECT_STORE = Path(os.getenv("PORTAL_OBJECT_STORE", DATA_DIR / "object-store"))
DEMO_DIR = ROOT / "demo"
CONTRACTS_DIR = ROOT / "contracts"
AGENTS_DIR = ROOT / "agents"
FRONTEND_DIR = ROOT / "frontend"


class ChatRequest(BaseModel):
    question: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OBJECT_STORE.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            create table if not exists domains (
                id text primary key,
                name text not null,
                owner text not null,
                description text not null
            );
            create table if not exists contracts (
                id text primary key,
                domain_id text not null,
                topic text not null,
                event_name text not null,
                version text not null,
                primary_keys text not null,
                schema_path text not null,
                description text not null
            );
            create table if not exists ingestion_runs (
                id text primary key,
                marker_id text not null,
                contract_id text not null,
                started_at text not null,
                completed_at text not null,
                status text not null,
                records_read integer not null,
                records_written integer not null,
                records_deduped integer not null,
                output_path text not null
            );
            create table if not exists catalog_tables (
                id text primary key,
                layer text not null,
                domain_id text not null,
                table_name text not null,
                source_contract_id text not null,
                storage_path text not null,
                record_count integer not null,
                updated_at text not null
            );
            create table if not exists data_lineage (
                id text primary key,
                source text not null,
                target text not null,
                relation text not null,
                contract_id text,
                run_id text
            );
            create table if not exists process_lineage (
                id text primary key,
                marker_id text not null,
                run_id text not null,
                step_name text not null,
                detail text not null,
                created_at text not null
            );
            """
        )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def reset_demo() -> dict[str, Any]:
    init_db()
    if DB_PATH.exists():
        DB_PATH.unlink()
    for file_path in OBJECT_STORE.glob("**/*"):
        if file_path.is_file() and file_path.name != ".gitkeep":
            file_path.unlink()
    init_db()
    with connect() as conn:
        conn.execute(
            "insert into domains values (?, ?, ?, ?)",
            (
                "commerce",
                "Retail Commerce",
                "Commerce Data Office",
                "Retail orders, payments, and shipment events used for the demo data platform.",
            ),
        )
        for contract in load_json(DEMO_DIR / "contracts.json"):
            conn.execute(
                "insert into contracts values (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    contract["id"],
                    contract["domain_id"],
                    contract["topic"],
                    contract["event_name"],
                    contract["version"],
                    json.dumps(contract["primary_keys"]),
                    contract["schema_path"],
                    contract["description"],
                ),
            )
    return {"status": "reset", "domains": 1, "contracts": len(load_json(DEMO_DIR / "contracts.json"))}


def ensure_demo() -> None:
    init_db()
    with connect() as conn:
        count = conn.execute("select count(*) from domains").fetchone()[0]
    if count == 0:
        reset_demo()


def contract_by_id(conn: sqlite3.Connection, contract_id: str) -> dict[str, Any]:
    result = rows(conn, "select * from contracts where id = ?", (contract_id,))
    if not result:
        raise HTTPException(status_code=404, detail=f"Unknown contract: {contract_id}")
    contract = result[0]
    contract["primary_keys"] = json.loads(contract["primary_keys"])
    return contract


def event_key(record: dict[str, Any], keys: list[str]) -> tuple[Any, ...]:
    return tuple(record.get(key) for key in keys)


def write_layer(layer: str, contract: dict[str, Any], records: list[dict[str, Any]], run_id: str) -> str:
    table_name = f"{contract['domain_id']}_{contract['event_name'].replace('.', '_')}"
    layer_dir = OBJECT_STORE / layer / contract["domain_id"] / table_name
    layer_dir.mkdir(parents=True, exist_ok=True)
    output = layer_dir / f"{run_id}.parquet.jsonl"
    with output.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
    return str(output.relative_to(ROOT))


def run_demo_ingestion() -> dict[str, Any]:
    ensure_demo()
    marker = load_json(DEMO_DIR / "markers" / "commerce_batch_001.json")
    run_summaries: list[dict[str, Any]] = []

    with connect() as conn:
        for item in marker["publications"]:
            contract = contract_by_id(conn, item["contract_id"])
            event_file = DEMO_DIR / item["event_file"]
            records = load_json(event_file)
            seen: set[tuple[Any, ...]] = set()
            deduped: list[dict[str, Any]] = []
            for record in records:
                key = event_key(record, contract["primary_keys"])
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(record)

            run_id = f"run_{uuid.uuid4().hex[:12]}"
            started = utc_now()
            output_paths = {layer: write_layer(layer, contract, deduped, run_id) for layer in ("intraday", "endofday", "analytics")}
            completed = utc_now()
            conn.execute(
                "insert into ingestion_runs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    marker["marker_id"],
                    contract["id"],
                    started,
                    completed,
                    "completed",
                    len(records),
                    len(deduped),
                    len(records) - len(deduped),
                    output_paths["analytics"],
                ),
            )
            for layer, output_path in output_paths.items():
                table_id = f"{layer}.{contract['domain_id']}.{contract['event_name']}"
                conn.execute(
                    "insert or replace into catalog_tables values (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        table_id,
                        layer,
                        contract["domain_id"],
                        contract["event_name"],
                        contract["id"],
                        output_path,
                        len(deduped),
                        completed,
                    ),
                )
                conn.execute(
                    "insert into data_lineage values (?, ?, ?, ?, ?, ?)",
                    (
                        f"lin_{uuid.uuid4().hex[:12]}",
                        contract["topic"],
                        table_id,
                        "ingested_to",
                        contract["id"],
                        run_id,
                    ),
                )
            for step, detail in (
                ("marker_discovered", f"Marker {marker['marker_id']} announced {contract['topic']}"),
                ("records_deduplicated", f"{len(records) - len(deduped)} duplicate records removed by {contract['primary_keys']}"),
                ("catalogs_written", "intraday, endofday, and analytics layers updated"),
            ):
                conn.execute(
                    "insert into process_lineage values (?, ?, ?, ?, ?, ?)",
                    (f"pl_{uuid.uuid4().hex[:12]}", marker["marker_id"], run_id, step, detail, utc_now()),
                )
            run_summaries.append(
                {
                    "run_id": run_id,
                    "contract_id": contract["id"],
                    "records_read": len(records),
                    "records_written": len(deduped),
                    "records_deduped": len(records) - len(deduped),
                    "output_path": output_paths["analytics"],
                }
            )
    return {"marker_id": marker["marker_id"], "runs": run_summaries}


def context_documents() -> list[str]:
    ensure_demo()
    docs: list[str] = []
    for path in sorted(AGENTS_DIR.glob("*.md")):
        docs.append(path.read_text(encoding="utf-8"))
    with connect() as conn:
        docs.append("Domains: " + json.dumps(rows(conn, "select * from domains"), default=str))
        docs.append("Contracts: " + json.dumps(rows(conn, "select * from contracts"), default=str))
        docs.append("Catalogs: " + json.dumps(rows(conn, "select * from catalog_tables"), default=str))
        docs.append("Ingestion runs: " + json.dumps(rows(conn, "select * from ingestion_runs"), default=str))
    return docs


def deterministic_answer(question: str) -> dict[str, Any]:
    q = question.lower()
    docs = context_documents()
    matched = [doc for doc in docs if any(token in doc.lower() for token in q.split() if len(token) > 3)]
    if not matched:
        matched = docs[:2]
    if any(term in q for term in ("lineage", "where", "flow")):
        answer = "Data lineage starts at commerce Kafka topics, moves through marker-based ingestion, and lands in intraday, endofday, and analytics catalog tables. Process lineage records marker discovery, deduplication, and catalog writes for each run."
    elif any(term in q for term in ("dedup", "primary", "duplicate")):
        answer = "Deduplication uses the primary keys declared by each event contract. The demo order contract uses order_id, payment uses payment_id, and shipment uses shipment_id."
    elif any(term in q for term in ("catalog", "iceberg", "layer")):
        answer = "The template models three catalog layers: intraday for fresh ingestion, endofday for closed historical state, and analytics for reporting-ready tables."
    else:
        answer = "This portal is a reusable template for contract-aware ingestion, historical catalog layers, lineage, process lineage, and scoped AI answers over local metadata."
    return {"mode": "deterministic", "answer": answer, "sources": [f"local_context_{idx + 1}" for idx, _ in enumerate(matched[:3])]}


def openai_answer(question: str) -> dict[str, Any] | None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    endpoint = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Answer only from the provided Data Intelligence Portal context."},
            {"role": "user", "content": "\n\n".join(context_documents()[:5]) + f"\n\nQuestion: {question}"},
        ],
        "temperature": 0.2,
    }
    req = request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
            return {"mode": "openai-compatible", "answer": body["choices"][0]["message"]["content"], "sources": ["local portal context"]}
    except Exception:
        return None


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_demo()
    yield


app = FastAPI(
    title="Data Intelligence Portal",
    description="Cloneable data intelligence portal template with demo ingestion, lineage, and AI answers.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "data-intelligence-portal"}


@app.post("/api/demo/reset")
def demo_reset() -> dict[str, Any]:
    return reset_demo()


@app.post("/api/ingestion-runs/demo")
def demo_ingestion() -> dict[str, Any]:
    return run_demo_ingestion()


@app.get("/api/domains")
def domains() -> list[dict[str, Any]]:
    ensure_demo()
    with connect() as conn:
        return rows(conn, "select * from domains order by id")


@app.get("/api/contracts")
def contracts() -> list[dict[str, Any]]:
    ensure_demo()
    with connect() as conn:
        data = rows(conn, "select * from contracts order by topic")
    for item in data:
        item["primary_keys"] = json.loads(item["primary_keys"])
        schema_path = ROOT / item["schema_path"]
        item["schema"] = schema_path.read_text(encoding="utf-8") if schema_path.exists() else ""
    return data


@app.get("/api/ingestion-runs")
def ingestion_runs() -> list[dict[str, Any]]:
    ensure_demo()
    with connect() as conn:
        return rows(conn, "select * from ingestion_runs order by started_at desc")


@app.get("/api/catalogs")
def catalogs() -> list[dict[str, Any]]:
    ensure_demo()
    with connect() as conn:
        return rows(conn, "select * from catalog_tables order by layer, table_name")


@app.get("/api/lineage/data")
def data_lineage() -> list[dict[str, Any]]:
    ensure_demo()
    with connect() as conn:
        return rows(conn, "select * from data_lineage order by target")


@app.get("/api/lineage/process")
def process_lineage() -> list[dict[str, Any]]:
    ensure_demo()
    with connect() as conn:
        return rows(conn, "select * from process_lineage order by created_at")


@app.post("/api/chat")
def chat(payload: ChatRequest) -> dict[str, Any]:
    if not payload.question.strip():
        raise HTTPException(status_code=400, detail="Question is required")
    return openai_answer(payload.question) or deterministic_answer(payload.question)


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
