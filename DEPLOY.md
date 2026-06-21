# Deploying the full app

The published site at **public.suranku.com is a static GitHub Pages showcase** — the apps
run in browser-only demo mode. For the full experience (repo scanning, persistence, AI), run
the **FastAPI app**, which serves the static site **and** `/api` from one origin. So you never
"wire Pages to a backend" — you deploy one self-contained image.

```
public.suranku.com  (Pages: static showcase)  ──"Run the full app →"──▶  the FastAPI image
```

## Tier 1 — GitHub Pages (already deployed)

`.github/workflows/pages.yml` publishes `site/` on every push to `main`; `site/CNAME` sets
`public.suranku.com`. Nothing to do. Static mode demonstrates the UI; scanning/AI show a
"connect the backend" notice and link here.

## Tier 2a — Self-host with Docker (recommended; secure for private data)

```bash
git clone https://github.com/Yamini-Suranku/suranku-public
cd suranku-public/apps/data-intelligence-portal
docker compose up --build      # full app at http://localhost:8080
```

This is the engagement path — "run it yourself, scan your own data." A **private** repo's
token stays on your machine; nothing is sent to a third party. Optional env (in `.env`):

| Var | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Native Claude answers (`ANTHROPIC_MODEL` defaults to `claude-opus-4-8`). |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` | Any OpenAI-compatible endpoint, incl. a local **Ollama** (`http://localhost:11434/v1`). |
| `OPENAI_TIMEOUT` | Raise for slow local models (e.g. `120`). |
| `PORTAL_SCAN_ROOT` | Folder the scanner may read for `local_path` sources (mount your repos here). |

## Tier 2b — Host a live full instance (Render / Fly.io)

Both deploy the **same Dockerfile** (`apps/data-intelligence-portal/Dockerfile`), which builds
from the repo root and serves frontend + API on port `8080`.

**Render** — push the repo, then in Render: *New → Blueprint* and pick this repo; it reads
[`render.yaml`](render.yaml). Set `ANTHROPIC_API_KEY` in the dashboard. (Free plan storage is
ephemeral — see persistence below.)

**Fly.io** —
```bash
fly launch --no-deploy        # edit the app name in fly.toml first
fly secrets set ANTHROPIC_API_KEY=...   # optional
fly deploy
```

Then point the Pages hub at it (e.g. a `app.suranku.com` CNAME + a "Launch the full app →"
link, already on the hub).

### AWS Lambda (serverless, scale-to-zero — best for low/sporadic traffic)

Pay-per-request with no idle cost. One container image serves the site **and** `/api` behind a
**Lambda Function URL** (no API Gateway, no CORS). Uses [`template.yaml`](template.yaml),
[`apps/data-intelligence-portal/Dockerfile.lambda`](apps/data-intelligence-portal/Dockerfile.lambda),
and `lambda_handler.py` (Mangum wraps the FastAPI app).

```bash
# prerequisites: AWS SAM CLI + Docker + an ECR repo (sam creates one with --guided)
sam build
sam deploy --guided --parameter-overrides AnthropicApiKey=YOUR_KEY   # key optional
# -> Outputs.PortalUrl is your app; link the Pages hub "Run the full app" at it.
```

Lambda specifics (already wired in the image):
- **Read-only filesystem** except `/tmp` — the image sets `PORTAL_DATA_DIR`, `PORTAL_DB`,
  `PORTAL_OBJECT_STORE`, and `PORTAL_SCAN_ROOT` under `/tmp`. So **data is ephemeral**
  (per warm container; gone on cold start). Perfect for a demo; for durable metadata use
  **EFS** mounted at `/tmp/data`, or move to **DynamoDB/RDS**.
- **Cold starts**: a container-image FastAPI cold start is ~1–3s; fine for low traffic.
  `EphemeralStorage` is 2 GB (for extracted repo archives) and timeout 120s (for scans) —
  tune in `template.yaml`.
- **Auth**: `FunctionUrlConfig.AuthType: NONE` makes it a public demo. For a private instance
  use `AWS_IAM`. Keep the shared-instance security rules below (public-URL/zip scanning only).
- Static-through-Lambda means each same-origin asset is an invocation — negligible at low
  traffic. If it grows, put `site/` on **S3 + CloudFront** and keep Lambda for `/api`.

### Persistence
Metadata is **SQLite at `/app/data`** — ephemeral by default on a PaaS (resets on redeploy).
For durable data, attach a 1 GB volume at `/app/data` (commented blocks in `render.yaml` /
`fly.toml`) or migrate to Postgres.

## Security — read before exposing a *shared* instance

A self-host instance is safe (it's your infra). A **public/shared** instance is different:

- **Do not accept private GitHub tokens on a shared backend.** Keep shared instances to
  **public repo URL + zip upload** only; private/token scanning belongs in self-host, where
  the token never leaves the user's machine.
- The scanner fetches URLs and reads archives. It already enforces a **GitHub host allowlist**,
  an **archive size cap**, and **request timeouts**, and parses SQL (never executes it). For a
  public endpoint also add **rate limiting** and tighter **egress/SSRF** controls at the edge.
- **Tighten CORS.** The app ships `allow_origins=["*"]` for easy local use; restrict it to your
  known origins before exposing the API.
- Set AI keys as **secrets**, never commit them.
