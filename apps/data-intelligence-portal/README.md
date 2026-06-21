# Data Intelligence Portal

A cloneable Suranku template for data intelligence: contracts, marker-driven ingestion, historical catalog layers, lineage, process lineage, and AI-assisted answers.

Hosted UI: `https://public.suranku.com`

The first demo uses a retail commerce domain with orders, payments, and shipments. It is intentionally lightweight so teams can understand the architecture before replacing the demo adapters with Kafka, Iceberg, S3, MinIO, or enterprise catalog services.

## What It Demonstrates

- Source domains that publish agreed events.
- Protobuf contracts with event names and primary keys.
- Marker-driven ingestion that starts after publication.
- Deduplication based on contract-defined primary keys.
- Intraday, end-of-day, and analytics catalog layers.
- Data lineage from topic to catalog table.
- Process lineage from marker to run to table write.
- AI-assisted answers over scoped local metadata.

## Quickstart

```bash
docker compose up --build
```

Open `http://localhost:8080`.

Use **Run ingestion** in the UI, or call the API:

```bash
curl -X POST http://localhost:8080/api/ingestion-runs/demo
curl http://localhost:8080/api/catalogs
curl http://localhost:8080/api/lineage/data
```

## Public UI On GitHub Pages

Suranku Public is the static GitHub Pages hub for free Suranku apps, demos, templates, and experiments. The Data Intelligence Portal is the first public app:

- Public hub: `https://public.suranku.com`
- Data Intelligence Portal: `https://public.suranku.com/data-intelligence-portal/`
- GitHub repository: `https://github.com/Yamini-Suranku/suranku-public` (this app lives under `apps/data-intelligence-portal/`)

The UI can be hosted directly from GitHub Pages. The included workflow publishes the repo's `site/` folder on every push to `main`, and `site/CNAME` configures the custom domain as `public.suranku.com`. This app's UI is `site/data-intelligence-portal/`.

In GitHub, enable:

1. Repository **Settings**.
2. **Pages**.
3. Source: **GitHub Actions**.
4. Custom domain: `public.suranku.com`.

Add this DNS record wherever `suranku.com` is managed:

| Type | Name/Host | Target |
| --- | --- | --- |
| CNAME | `public` | `yamini-suranku.github.io` |

After GitHub validates the certificate, enable **Enforce HTTPS**.

The Pages version runs as a browser-only demo when the FastAPI backend is not available. It uses the same UI and simulates reset, ingestion, catalogs, lineage, process lineage, and chat locally in the browser.

For the full persistent API experience, run the Docker/FastAPI version locally or deploy the backend separately.

## Test the live demo (repo scan → column-level lineage)

The live app at `https://app.suranku.com/data-intelligence-portal/` runs the full backend on AWS
Lambda. Storage is **ephemeral by design** (`/tmp`, per warm container, reset on cold start) — so
**do the scan and view it in the same session**.

**A. One-click bundled sample (easiest):**
1. **Scan** tab → **"Scan sample repo"** → wait for the summary (8 files / 12 tables / 33 column edges).
2. **Lineage Graph** tab → you'll see `public.* → stg_* → dim_/fct_ → mart_* →` Tableau + PowerBI report nodes.
3. **Click a mart node** (e.g. `analytics.mart_revenue`) → the **column-level** lineage renders, source → target columns with transformations.

**B. Your own public GitHub repo:**
1. **Scan** tab → **GitHub (public)** → e.g. `https://github.com/dbt-labs/jaffle_shop` → **Scan**.
2. **Lineage Graph** → click a model node → column lineage.

**C. Zip upload:** **Scan** tab → **Upload .zip** of a repo containing `.sql` / `.twb` / `.pbit` → **Scan** → graph → click a node.

Private-token scanning is intentionally **not** offered on the shared backend (the token would
leave your machine). Use the self-hosted Docker run below for private repos — the token stays local.

## Local Python Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --port 8080
```

## Optional AI Provider

The assistant works without API keys using deterministic local context. When a
key is configured, the `/api/chat` endpoint tries providers in this order:
**native Anthropic → OpenAI-compatible → deterministic local responder**.

### Native Claude / Anthropic (preferred)

Uses the official [`anthropic`](https://github.com/anthropics/anthropic-sdk-python)
SDK (already in `requirements.txt`). Get a key at
<https://console.anthropic.com/>, then copy `.env.example` to `.env` and set:

```bash
export ANTHROPIC_API_KEY=...
export ANTHROPIC_MODEL=claude-opus-4-8   # optional; this is the default
```

### OpenAI-compatible (fallback)

Any **OpenAI-compatible** Chat Completions endpoint (OpenAI, Azure OpenAI, Groq,
Together, OpenRouter, a local Ollama/LM Studio server, …):

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-4o-mini
```

If a provider call fails or no key is set, answers fall back to the built-in
deterministic responder, so the portal always works. The chat response `mode`
field reports which path answered (`anthropic`, `openai-compatible`, or
`deterministic`).

## Tests

```bash
pip install -r requirements.txt
python -m pytest
```

The suite covers the ingestion/lineage logic directly and the HTTP API via
`fastapi.testclient` (health, reset, ingestion, catalogs/lineage counts, chat
validation, deterministic fallback, static frontend, and path-traversal
rejection). CI runs them on every push and pull request
(`.github/workflows/ci.yml`).

## Adapt The Template

1. Add contracts in `demo/contracts.json`.
2. Add Protobuf schemas under `contracts/protobuf/<domain>/`.
3. Add sample events under `demo/events/<domain>/`.
4. Add marker files under `demo/markers/`.
5. Declare primary keys for each event.
6. Replace demo readers/writers with production adapters as needed.

## Build & import in the UI

The **Build** tab lets you define everything by hand — domains, contracts
(Kafka topic, event name, version, primary keys, Protobuf schema), sample
events, and lineage edges — or **import** a JSON bundle / upload a `.proto`
file. Then **Run ingestion** dedupes by primary key and builds the catalog
layers and lineage. The **Lineage Graph** tab renders interactive D3 force
graphs (drag, zoom, hover) for both data and process lineage.

- **Backend mode** persists everything in SQLite via the authoring API.
- **Static (GitHub Pages) mode** persists to the browser's `localStorage`, so
  your definitions survive reloads on `public.suranku.com`.

## Self-monitoring

The **Monitoring** tab shows dependency liveness/readiness when the backend is
running: `GET /api/health` (liveness) and `GET /api/readiness` (database,
object store, AI provider config, and seed data, each with latencies). In
static mode it reports browser-demo status instead.

## AI Agents (installable)

`site/agents/` is a public catalog of reusable agents (served at
`public.suranku.com/agents/…` and shown in the **AI Agents** tab). Each agent is
a portable `*.md` with Claude Code-compatible front-matter plus a
provider-agnostic system prompt, use cases, an example, and install steps —
usable in Claude or any OpenAI-compatible provider. To add one, drop a `<id>.md`
in `site/agents/` and add an entry to `index.json`. `GET /api/agents` serves
the same catalog.

## API Highlights

- `GET /api/health` — liveness · `GET /api/readiness` — dependency readiness
- `POST /api/demo/reset` · `POST /api/ingestion-runs/demo`
- `POST /api/domains` · `POST /api/contracts` · `POST /api/events`
- `POST /api/ingestion-runs` — ingest any contract that has stored events
- `POST /api/lineage/data` · `POST /api/lineage/process`
- `GET /api/domains` · `/api/contracts` · `/api/events` · `/api/ingestion-runs`
  · `/api/catalogs` · `/api/lineage/data` · `/api/lineage/process`
- `GET /api/agents` · `POST /api/chat`

## License

Apache License 2.0. See `LICENSE`.

Suranku names and logos are not licensed under Apache 2.0. See `TRADEMARKS.md`.
