from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request

import shutil
import tempfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


ROOT = Path(os.getenv("PORTAL_HOME", Path(__file__).resolve().parents[2]))
# Writable runtime dir. Defaults under ROOT, but on read-only roots (AWS Lambda)
# point it at a writable path, e.g. PORTAL_DATA_DIR=/tmp/data.
DATA_DIR = Path(os.getenv("PORTAL_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.getenv("PORTAL_DB", DATA_DIR / "portal.db"))
OBJECT_STORE = Path(os.getenv("PORTAL_OBJECT_STORE", DATA_DIR / "object-store"))
DEMO_DIR = ROOT / "demo"
CONTRACTS_DIR = ROOT / "contracts"
AGENTS_DIR = ROOT / "agents"
# Root the repo scanner is allowed to read. Configured source paths resolve under
# here (safe_path guards traversal). Mount your repos into this dir in Docker.
SCAN_ROOT = Path(os.getenv("PORTAL_SCAN_ROOT", ROOT / "repos"))
# Published static site (hub + all app UIs + shared assets/learn/agents). In the
# suranku-public monorepo it lives at the repo root (../../site relative to this app),
# not under the app dir. Override with PORTAL_SITE (e.g. the Docker image copies it to /app/site).
FRONTEND_DIR = Path(os.getenv("PORTAL_SITE", Path(__file__).resolve().parents[4] / "site"))


class ChatRequest(BaseModel):
    question: str


class DomainIn(BaseModel):
    id: str | None = None
    name: str
    owner: str = ""
    description: str = ""


class ContractIn(BaseModel):
    domain_id: str
    event_name: str
    # "kafka" (event/topic + Protobuf) or "relational" (a database table, e.g. Postgres).
    source_type: str = "kafka"
    topic: str = ""  # Kafka topic, or schema.table for a relational source
    version: str = "v1"
    primary_keys: list[str] = []  # required for kafka (dedup); optional for relational
    schema_text: str = ""
    description: str = ""


class EventBatchIn(BaseModel):
    contract_id: str
    records: list[dict[str, Any]]


class DataLineageIn(BaseModel):
    source: str
    target: str
    relation: str = "derived_from"


class ProcessLineageIn(BaseModel):
    marker_id: str
    run_id: str
    step_name: str
    detail: str = ""


class ScanSourceIn(BaseModel):
    name: str
    # "local_path" (under SCAN_ROOT) | "github_public" | "github_private"
    kind: str = "local_path"
    path: str = ""        # for local_path
    repo_url: str = ""    # for github_* (https://github.com/<owner>/<repo> or <owner>/<repo>)
    ref: str = ""         # optional git ref/branch/tag
    subdir: str = ""      # optional sub-path within the repo to scan
    sql_globs: list[str] = []
    report_globs: list[str] = []
    naming_conventions: list[dict[str, Any]] = []
    dialect: str = ""


class RunScanIn(BaseModel):
    # Per-run token for private GitHub repos. Never stored.
    token: str = ""


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or f"id-{uuid.uuid4().hex[:8]}"


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
                schema_path text not null default '',
                schema_text text,
                description text not null default '',
                source_type text not null default 'kafka'
            );
            create table if not exists events (
                id text primary key,
                contract_id text not null,
                payload text not null,
                created_at text not null
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
            create table if not exists scan_sources (
                id text primary key,
                name text not null,
                kind text not null default 'local_path',
                path text not null default '',
                repo_url text not null default '',
                ref text not null default '',
                subdir text not null default '',
                sql_globs text not null default '[]',
                report_globs text not null default '[]',
                naming_conventions text not null default '[]',
                dialect text not null default '',
                created_at text not null
            );
            create table if not exists scan_runs (
                id text primary key,
                source_id text not null,
                started_at text not null,
                completed_at text not null,
                status text not null,
                files integer not null default 0,
                tables integer not null default 0,
                columns integer not null default 0,
                warnings text not null default '[]'
            );
            create table if not exists scanned_assets (
                id text primary key,
                scan_id text not null,
                source_id text not null,
                asset_type text not null,
                path text not null,
                name text not null,
                created_at text not null
            );
            create table if not exists column_lineage (
                id text primary key,
                scan_id text,
                asset text,
                source_table text,
                source_column text,
                target_table text not null,
                target_column text not null,
                transformation text,
                created_at text not null
            );
            """
        )
        # Migration for DBs created before schema_text existed.
        columns = {row[1] for row in conn.execute("pragma table_info(contracts)")}
        if "schema_text" not in columns:
            conn.execute("alter table contracts add column schema_text text")
        if "source_type" not in columns:
            conn.execute("alter table contracts add column source_type text not null default 'kafka'")
        # Migration: scan_sources gained github fields.
        ss_columns = {row[1] for row in conn.execute("pragma table_info(scan_sources)")}
        for col in ("repo_url", "ref", "subdir"):
            if col not in ss_columns:
                conn.execute(f"alter table scan_sources add column {col} text not null default ''")
        # Migration: data_lineage gained asset/scan provenance for scanned edges.
        dl_columns = {row[1] for row in conn.execute("pragma table_info(data_lineage)")}
        if "asset" not in dl_columns:
            conn.execute("alter table data_lineage add column asset text")
        if "scan_id" not in dl_columns:
            conn.execute("alter table data_lineage add column scan_id text")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_path(base: Path, relative: str) -> Path:
    """Resolve `relative` under `base`, rejecting traversal outside it.

    Contracts/markers carry paths from data files; a cloned template may load
    untrusted ones, so never read outside the intended directory.
    """
    base_resolved = base.resolve()
    candidate = (base_resolved / relative).resolve()
    if candidate != base_resolved and base_resolved not in candidate.parents:
        raise HTTPException(status_code=400, detail=f"Path escapes allowed directory: {relative}")
    return candidate


def reset_demo() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OBJECT_STORE.mkdir(parents=True, exist_ok=True)
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
                """insert into contracts
                   (id, domain_id, topic, event_name, version, primary_keys, schema_path, description)
                   values (?, ?, ?, ?, ?, ?, ?, ?)""",
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


def ingest_records(
    conn: sqlite3.Connection,
    contract: dict[str, Any],
    records: list[dict[str, Any]],
    marker_id: str,
) -> dict[str, Any]:
    """Dedupe records by the contract's primary keys, write the three catalog
    layers, and record the run, catalogs, and data + process lineage."""
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
            marker_id,
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
            (table_id, layer, contract["domain_id"], contract["event_name"], contract["id"], output_path, len(deduped), completed),
        )
        conn.execute(
            "insert into data_lineage (id, source, target, relation, contract_id, run_id) values (?, ?, ?, ?, ?, ?)",
            (f"lin_{uuid.uuid4().hex[:12]}", contract["topic"], table_id, "ingested_to", contract["id"], run_id),
        )
    for step, detail in (
        ("marker_discovered", f"Marker {marker_id} announced {contract['topic']}"),
        ("records_deduplicated", f"{len(records) - len(deduped)} duplicate records removed by {contract['primary_keys']}"),
        ("catalogs_written", "intraday, endofday, and analytics layers updated"),
    ):
        conn.execute(
            "insert into process_lineage values (?, ?, ?, ?, ?, ?)",
            (f"pl_{uuid.uuid4().hex[:12]}", marker_id, run_id, step, detail, utc_now()),
        )
    return {
        "run_id": run_id,
        "contract_id": contract["id"],
        "records_read": len(records),
        "records_written": len(deduped),
        "records_deduped": len(records) - len(deduped),
        "output_path": output_paths["analytics"],
    }


def run_demo_ingestion() -> dict[str, Any]:
    ensure_demo()
    marker = load_json(DEMO_DIR / "markers" / "commerce_batch_001.json")
    run_summaries: list[dict[str, Any]] = []
    with connect() as conn:
        for item in marker["publications"]:
            contract = contract_by_id(conn, item["contract_id"])
            records = load_json(safe_path(DEMO_DIR, item["event_file"]))
            run_summaries.append(ingest_records(conn, contract, records, marker["marker_id"]))
    return {"marker_id": marker["marker_id"], "runs": run_summaries}


def run_ingestion() -> dict[str, Any]:
    """Generalized ingestion over every contract that has stored events
    (from the authoring API), not just the bundled demo."""
    init_db()
    marker_id = f"manual-{uuid.uuid4().hex[:8]}"
    summaries: list[dict[str, Any]] = []
    with connect() as conn:
        for contract in rows(conn, "select * from contracts"):
            contract["primary_keys"] = json.loads(contract["primary_keys"])
            stored = rows(conn, "select payload from events where contract_id = ?", (contract["id"],))
            records = [json.loads(item["payload"]) for item in stored]
            if not records:
                continue
            summaries.append(ingest_records(conn, contract, records, marker_id))
    if not summaries:
        raise HTTPException(status_code=400, detail="No contracts have events yet. Add events, then run ingestion.")
    return {"marker_id": marker_id, "runs": summaries}


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


def anthropic_answer(question: str) -> dict[str, Any] | None:
    """Native Claude/Anthropic answer via the official SDK (preferred provider)."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
    try:
        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        message = client.messages.create(
            model=model,
            max_tokens=1024,
            system=(
                "You are the Data Intelligence Portal assistant. Answer only from the "
                "provided portal context. If the context does not contain the answer, "
                "say so plainly. Respond with the final answer only — concise, no preamble."
            ),
            messages=[
                {
                    "role": "user",
                    "content": "\n\n".join(context_documents()[:5]) + f"\n\nQuestion: {question}",
                }
            ],
        )
        answer = "".join(block.text for block in message.content if block.type == "text").strip()
        if not answer:
            return None
        return {"mode": "anthropic", "answer": answer, "sources": ["local portal context"]}
    except Exception:
        return None


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
        # Local models (Ollama, LM Studio) are slower than cloud APIs on a full
        # context, so allow a longer timeout via OPENAI_TIMEOUT (default 20s).
        timeout = float(os.getenv("OPENAI_TIMEOUT", "20"))
        with request.urlopen(req, timeout=timeout) as response:
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
        schema = item.get("schema_text") or ""
        if not schema and item.get("schema_path"):
            schema_path = safe_path(ROOT, item["schema_path"])
            schema = schema_path.read_text(encoding="utf-8") if schema_path.is_file() else ""
        item["schema"] = schema
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
    return (
        anthropic_answer(payload.question)
        or openai_answer(payload.question)
        or deterministic_answer(payload.question)
    )


# --------------------------------------------------------------- authoring API

@app.post("/api/domains", status_code=201)
def create_domain(payload: DomainIn) -> dict[str, Any]:
    init_db()
    domain_id = payload.id or slugify(payload.name)
    with connect() as conn:
        conn.execute(
            "insert or replace into domains values (?, ?, ?, ?)",
            (domain_id, payload.name, payload.owner, payload.description),
        )
    return {"id": domain_id, "name": payload.name, "owner": payload.owner, "description": payload.description}


@app.post("/api/contracts", status_code=201)
def create_contract(payload: ContractIn) -> dict[str, Any]:
    # Kafka sources need primary keys for deduplication; relational sources don't.
    if payload.source_type == "kafka" and not payload.primary_keys:
        raise HTTPException(status_code=400, detail="At least one primary key is required for a Kafka source")
    if not payload.topic.strip():
        label = "table" if payload.source_type == "relational" else "Kafka topic"
        raise HTTPException(status_code=400, detail=f"A {label} is required")
    init_db()
    contract_id = f"{payload.domain_id}.{payload.event_name}.{payload.version}"
    with connect() as conn:
        conn.execute(
            "insert or ignore into domains values (?, ?, ?, ?)",
            (payload.domain_id, payload.domain_id, "", ""),
        )
        conn.execute(
            """insert or replace into contracts
               (id, domain_id, topic, event_name, version, primary_keys, schema_path, schema_text, description, source_type)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                contract_id,
                payload.domain_id,
                payload.topic,
                payload.event_name,
                payload.version,
                json.dumps(payload.primary_keys),
                "",
                payload.schema_text,
                payload.description,
                payload.source_type,
            ),
        )
    return {"id": contract_id, **payload.model_dump()}


@app.post("/api/events", status_code=201)
def add_events(payload: EventBatchIn) -> dict[str, Any]:
    init_db()
    with connect() as conn:
        contract_by_id(conn, payload.contract_id)  # validates existence (404 otherwise)
        for record in payload.records:
            conn.execute(
                "insert into events values (?, ?, ?, ?)",
                (f"ev_{uuid.uuid4().hex[:12]}", payload.contract_id, json.dumps(record), utc_now()),
            )
    return {"contract_id": payload.contract_id, "added": len(payload.records)}


@app.get("/api/events")
def list_events(contract_id: str | None = None) -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        if contract_id:
            data = rows(conn, "select * from events where contract_id = ? order by created_at", (contract_id,))
        else:
            data = rows(conn, "select * from events order by created_at")
    for item in data:
        item["payload"] = json.loads(item["payload"])
    return data


@app.post("/api/lineage/data", status_code=201)
def add_data_lineage(payload: DataLineageIn) -> dict[str, Any]:
    init_db()
    lineage_id = f"lin_{uuid.uuid4().hex[:12]}"
    with connect() as conn:
        conn.execute(
            "insert into data_lineage (id, source, target, relation, contract_id, run_id) values (?, ?, ?, ?, ?, ?)",
            (lineage_id, payload.source, payload.target, payload.relation, None, None),
        )
    return {"id": lineage_id, **payload.model_dump()}


@app.post("/api/lineage/process", status_code=201)
def add_process_lineage(payload: ProcessLineageIn) -> dict[str, Any]:
    init_db()
    lineage_id = f"pl_{uuid.uuid4().hex[:12]}"
    with connect() as conn:
        conn.execute(
            "insert into process_lineage values (?, ?, ?, ?, ?, ?)",
            (lineage_id, payload.marker_id, payload.run_id, payload.step_name, payload.detail, utc_now()),
        )
    return {"id": lineage_id, **payload.model_dump()}


@app.post("/api/ingestion-runs")
def generalized_ingestion() -> dict[str, Any]:
    return run_ingestion()


# ------------------------------------------------------------------- repo scanner

def _persist_scan(conn: sqlite3.Connection, source: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Persist scan_run + assets + table/column lineage; return the run summary.

    Re-scanning a source is idempotent: prior scanned lineage + assets for this
    source are cleared first so edges don't accumulate across runs.
    """
    prior_scans = [r["id"] for r in rows(conn, "select id from scan_runs where source_id = ?", (source["id"],))]
    if prior_scans:
        placeholders = ",".join("?" for _ in prior_scans)
        conn.execute(f"delete from data_lineage where scan_id in ({placeholders})", prior_scans)
        conn.execute(f"delete from column_lineage where scan_id in ({placeholders})", prior_scans)
    conn.execute("delete from scanned_assets where source_id = ?", (source["id"],))
    scan_id = uuid.uuid4().hex
    now = utc_now()
    asset_ids: dict[str, str] = {}
    for asset in result["assets"]:
        aid = uuid.uuid4().hex
        asset_ids[asset["name"]] = aid
        conn.execute(
            "insert into scanned_assets (id, scan_id, source_id, asset_type, path, name, created_at)"
            " values (?, ?, ?, ?, ?, ?, ?)",
            (aid, scan_id, source["id"], asset["asset_type"], asset["path"], asset["name"], now),
        )
    for edge in result["table_edges"]:
        conn.execute(
            "insert into data_lineage (id, source, target, relation, contract_id, run_id, asset, scan_id)"
            " values (?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, edge["source"], edge["target"], edge["relation"], None, None, edge.get("asset"), scan_id),
        )
    for ce in result["column_edges"]:
        conn.execute(
            "insert into column_lineage (id, scan_id, asset, source_table, source_column,"
            " target_table, target_column, transformation, created_at)"
            " values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, scan_id, ce.get("asset"), ce.get("source_table"), ce.get("source_column"),
             ce["target_table"], ce["target_column"], ce.get("transformation"), now),
        )
    summary = {
        "id": scan_id,
        "source_id": source["id"],
        "started_at": now,
        "completed_at": utc_now(),
        "status": "completed",
        "files": result["files"],
        "tables": len(result["tables"]),
        "columns": len(result["column_edges"]),
        "warnings": result["warnings"],
    }
    conn.execute(
        "insert into scan_runs (id, source_id, started_at, completed_at, status, files, tables, columns, warnings)"
        " values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (summary["id"], summary["source_id"], summary["started_at"], summary["completed_at"], summary["status"],
         summary["files"], summary["tables"], summary["columns"], json.dumps(summary["warnings"])),
    )
    return summary


SCAN_COLS = ("id", "name", "kind", "path", "repo_url", "ref", "subdir",
             "sql_globs", "report_globs", "naming_conventions", "dialect", "created_at")


def _scan_and_persist(conn: sqlite3.Connection, source: dict[str, Any], base: str | Path) -> dict[str, Any]:
    from .scanner import scan_repo  # imported lazily so the app starts without sqlglot

    if not Path(base).is_dir():
        raise HTTPException(status_code=400, detail="Scan path not found")
    result = scan_repo(
        base,
        sql_globs=json.loads(source.get("sql_globs") or "[]") or None,
        report_globs=json.loads(source.get("report_globs") or "[]") or None,
        naming_conventions=json.loads(source.get("naming_conventions") or "[]"),
        dialect=source.get("dialect") or None,
    )
    return _persist_scan(conn, source, result)


def _resolve_github_base(source: dict[str, Any], token: str) -> tuple[Path, str]:
    """Fetch a GitHub repo into a temp dir; return (base_to_scan, tmpdir_to_clean)."""
    from .scanner import github_fetch as gh

    if source["kind"] == "github_private" and not token:
        raise HTTPException(status_code=400, detail="A GitHub token is required for a private repo")
    try:
        root, tmp = gh.fetch_to_tempdir(source["repo_url"], ref=source.get("ref", ""), token=token or None)
    except gh.FetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    subdir = (source.get("subdir") or "").strip().strip("/")
    base = safe_path(root, subdir) if subdir else root
    return base, tmp


@app.post("/api/scan/sources", status_code=201)
def create_scan_source(payload: ScanSourceIn) -> dict[str, Any]:
    kind = payload.kind or "local_path"
    if kind == "local_path":
        if not payload.path.strip():
            raise HTTPException(status_code=400, detail="A path is required for a local source")
        safe_path(SCAN_ROOT, payload.path)  # reject traversal outside SCAN_ROOT
    elif kind in ("github_public", "github_private"):
        from .scanner.github_fetch import FetchError, parse_repo
        try:
            parse_repo(payload.repo_url)
        except FetchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=400, detail=f"Unknown source kind: {kind}")
    ensure_demo()
    record = {
        "id": uuid.uuid4().hex,
        "name": payload.name,
        "kind": kind,
        "path": payload.path,
        "repo_url": payload.repo_url,
        "ref": payload.ref,
        "subdir": payload.subdir,
        "sql_globs": json.dumps(payload.sql_globs),
        "report_globs": json.dumps(payload.report_globs),
        "naming_conventions": json.dumps(payload.naming_conventions),
        "dialect": payload.dialect,
        "created_at": utc_now(),
    }
    with connect() as conn:
        conn.execute(
            f"insert into scan_sources ({', '.join(SCAN_COLS)}) values ({', '.join('?' for _ in SCAN_COLS)})",
            tuple(record[k] for k in SCAN_COLS),
        )
    return record


@app.get("/api/scan/sources")
def list_scan_sources() -> list[dict[str, Any]]:
    ensure_demo()
    with connect() as conn:
        data = rows(conn, "select * from scan_sources order by created_at desc")
    for item in data:
        for field in ("sql_globs", "report_globs", "naming_conventions"):
            item[field] = json.loads(item[field] or "[]")
    return data


@app.post("/api/scan/sources/{source_id}/run")
def run_scan_source(source_id: str, payload: RunScanIn | None = None) -> dict[str, Any]:
    ensure_demo()
    token = (payload.token if payload else "") or ""
    with connect() as conn:
        found = rows(conn, "select * from scan_sources where id = ?", (source_id,))
        if not found:
            raise HTTPException(status_code=404, detail="Scan source not found")
        source = found[0]
        tmp = None
        try:
            if source["kind"] in ("github_public", "github_private"):
                base, tmp = _resolve_github_base(source, token)
            else:
                base = safe_path(SCAN_ROOT, source["path"])
            summary = _scan_and_persist(conn, source, base)
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
    return summary


@app.post("/api/scan/upload")
async def scan_upload(request: Request, name: str = "Uploaded repo", dialect: str = "", subdir: str = "") -> dict[str, Any]:
    """Scan a user-uploaded .zip (POST the raw zip bytes as the body)."""
    from .scanner import github_fetch as gh

    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload — POST the .zip bytes as the request body")
    ensure_demo()
    tmp = tempfile.mkdtemp(prefix="dip-upload-")
    try:
        try:
            root = gh.extract_zip_bytes(data, tmp)
        except gh.FetchError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        sub = (subdir or "").strip().strip("/")
        base = safe_path(root, sub) if sub else root
        source = {
            "id": uuid.uuid4().hex, "name": name, "kind": "upload_zip", "path": "",
            "repo_url": "", "ref": "", "subdir": sub,
            "sql_globs": "[]", "report_globs": "[]", "naming_conventions": "[]",
            "dialect": dialect, "created_at": utc_now(),
        }
        with connect() as conn:
            conn.execute(
                f"insert into scan_sources ({', '.join(SCAN_COLS)}) values ({', '.join('?' for _ in SCAN_COLS)})",
                tuple(source[k] for k in SCAN_COLS),
            )
            summary = _scan_and_persist(conn, source, base)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return summary


@app.post("/api/scan/demo")
def scan_demo() -> dict[str, Any]:
    """Register-or-reuse a scan source for the bundled Postgres sample repo and scan it."""
    from .scanner import scan_repo

    ensure_demo()
    base = SCAN_ROOT / "sample"
    if not base.is_dir():
        raise HTTPException(status_code=400, detail="Bundled sample repo not found under the scan root")
    with connect() as conn:
        existing = rows(conn, "select * from scan_sources where name = ?", ("Sample (Postgres)",))
        if existing:
            source = existing[0]
        else:
            source = {
                "id": uuid.uuid4().hex,
                "name": "Sample (Postgres)",
                "kind": "local_path",
                "path": "sample",
                "sql_globs": json.dumps(["**/*.sql"]),
                "report_globs": json.dumps(["**/*.twb", "**/*.twbx", "**/*.pbix", "**/*.pbit"]),
                "naming_conventions": json.dumps([]),
                "dialect": "postgres",
                "created_at": utc_now(),
            }
            conn.execute(
                "insert into scan_sources (id, name, kind, path, sql_globs, report_globs, naming_conventions, dialect, created_at)"
                " values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(source[k] for k in ("id", "name", "kind", "path", "sql_globs", "report_globs", "naming_conventions", "dialect", "created_at")),
            )
        result = scan_repo(
            safe_path(SCAN_ROOT, source["path"]),
            sql_globs=json.loads(source["sql_globs"] or "[]") or None,
            report_globs=json.loads(source["report_globs"] or "[]") or None,
            naming_conventions=json.loads(source["naming_conventions"] or "[]"),
            dialect=source["dialect"] or None,
        )
        summary = _persist_scan(conn, source, result)
    return summary


@app.get("/api/scan/runs")
def list_scan_runs() -> list[dict[str, Any]]:
    ensure_demo()
    with connect() as conn:
        data = rows(conn, "select * from scan_runs order by started_at desc")
    for item in data:
        item["warnings"] = json.loads(item["warnings"] or "[]")
    return data


@app.get("/api/scan/assets")
def list_scanned_assets() -> list[dict[str, Any]]:
    ensure_demo()
    with connect() as conn:
        return rows(conn, "select * from scanned_assets order by created_at desc, name")


@app.get("/api/lineage/columns")
def column_lineage(table: str | None = None) -> list[dict[str, Any]]:
    ensure_demo()
    with connect() as conn:
        if table:
            return rows(
                conn,
                "select * from column_lineage where source_table = ? or target_table = ? order by target_table, target_column",
                (table, table),
            )
        return rows(conn, "select * from column_lineage order by target_table, target_column")


# ------------------------------------------------------------ self-monitoring

def _check(name: str, fn) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        detail = fn()
        status = "ok"
    except Exception as err:  # noqa: BLE001 - report any failure as degraded
        detail = str(err)
        status = "fail"
    return {"name": name, "status": status, "detail": detail, "latency_ms": round((time.perf_counter() - start) * 1000, 2)}


@app.get("/api/readiness")
def readiness(probe: int = 0) -> dict[str, Any]:
    """Readiness probe over the app's dependencies (liveness is /api/health)."""

    def check_database() -> str:
        with connect() as conn:
            conn.execute("select 1").fetchone()
        return "connected"

    def check_object_store() -> str:
        OBJECT_STORE.mkdir(parents=True, exist_ok=True)
        probe_file = OBJECT_STORE / ".readiness"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
        return f"writable at {OBJECT_STORE.relative_to(ROOT)}"

    def check_ai_provider() -> str:
        if os.getenv("ANTHROPIC_API_KEY"):
            model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
            return f"configured — Anthropic ({model})"
        if not os.getenv("OPENAI_API_KEY"):
            return "not configured — using deterministic local answers"
        base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        if probe:
            with request.urlopen(request.Request(base, method="GET"), timeout=5):
                pass
            return f"configured and reachable — OpenAI-compatible ({base})"
        return f"configured — OpenAI-compatible ({base})"

    def check_seed() -> str:
        with connect() as conn:
            domains_count = conn.execute("select count(*) from domains").fetchone()[0]
            contracts_count = conn.execute("select count(*) from contracts").fetchone()[0]
        return f"{domains_count} domains, {contracts_count} contracts"

    def check_scanner() -> str:
        try:
            import sqlglot  # noqa: F401
        except ImportError:
            return "sqlglot not installed — repo scanning disabled"
        SCAN_ROOT.mkdir(parents=True, exist_ok=True)
        return f"ready — sqlglot available, scan root {SCAN_ROOT.name}/"

    checks = [
        _check("database", check_database),
        _check("object_store", check_object_store),
        _check("ai_provider", check_ai_provider),
        _check("scanner", check_scanner),
        _check("seed_data", check_seed),
    ]
    # ai_provider not being configured is informational, not a failure.
    critical = [c for c in checks if c["name"] in {"database", "object_store"}]
    overall = "ready" if all(c["status"] == "ok" for c in critical) else "degraded"
    return {"status": overall, "service": "data-intelligence-portal", "checks": checks}


# --------------------------------------------------------------- agents catalog

AGENTS_REGISTRY = FRONTEND_DIR / "agents" / "index.json"


@app.get("/api/agents")
def list_agents() -> Any:
    if AGENTS_REGISTRY.is_file():
        return load_json(AGENTS_REGISTRY)
    return []


@app.middleware("http")
async def serve_static_directory_index(request: Request, call_next):
    # Lambda/Mangum drops the trailing slash from the ASGI path, which makes
    # StaticFiles(html=True) emit a self-referential 307 for a directory URL like
    # /data-intelligence-portal/ — an infinite redirect loop on Lambda (works fine
    # under native uvicorn, which preserves the slash). Resolve the directory's
    # index.html ourselves so StaticFiles serves a file and never redirects. Works
    # with or without the trailing slash; API paths (no index.html) are untouched.
    if request.method in ("GET", "HEAD"):
        rel = request.scope.get("path", "").strip("/")
        if rel and ".." not in rel and not rel.startswith("api/") and rel != "api":
            directory = FRONTEND_DIR / rel
            if directory.is_dir() and (directory / "index.html").is_file():
                request.scope["path"] = "/" + rel + "/index.html"
    return await call_next(request)


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
