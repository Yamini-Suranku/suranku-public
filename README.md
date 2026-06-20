# Data Intelligence Portal

A cloneable Suranku template for data intelligence: contracts, marker-driven ingestion, historical catalog layers, lineage, process lineage, and AI-assisted answers.

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

## Local Python Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload --port 8080
```

## Optional AI Provider

The assistant works without API keys using deterministic local context. To use an OpenAI-compatible provider:

```bash
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://api.openai.com/v1
export OPENAI_MODEL=gpt-4o-mini
```

## Adapt The Template

1. Add contracts in `demo/contracts.json`.
2. Add Protobuf schemas under `contracts/protobuf/<domain>/`.
3. Add sample events under `demo/events/<domain>/`.
4. Add marker files under `demo/markers/`.
5. Declare primary keys for each event.
6. Replace demo readers/writers with production adapters as needed.

## API Highlights

- `GET /api/health`
- `POST /api/demo/reset`
- `POST /api/ingestion-runs/demo`
- `GET /api/domains`
- `GET /api/contracts`
- `GET /api/ingestion-runs`
- `GET /api/catalogs`
- `GET /api/lineage/data`
- `GET /api/lineage/process`
- `POST /api/chat`

## License

Apache License 2.0. See `LICENSE`.

Suranku names and logos are not licensed under Apache 2.0. See `TRADEMARKS.md`.
