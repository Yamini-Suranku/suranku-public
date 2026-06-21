# Suranku Public

Free, open public apps, templates, and reference designs from Suranku — built to
**democratize the practice of responsible AI**. This is a monorepo: one published
static site plus the self-hostable source for each app.

- **Live site:** https://public.suranku.com
- **Marketing site:** https://suranku.com

## Layout

```
suranku-public/
├─ site/                          # GitHub Pages root (published to public.suranku.com)
│  ├─ index.html                  #   the hub — lists all public apps
│  ├─ assets/  learn/  agents/    #   shared across apps (styles, glossary, agents catalog)
│  └─ data-intelligence-portal/   #   an app's UI  → /data-intelligence-portal/
├─ apps/                          # self-hostable source, one dir per app
│  └─ data-intelligence-portal/   #   backend/ demo/ contracts/ tests/ Dockerfile + README
└─ .github/workflows/             # pages.yml (publish site/) · ci.yml (per-app tests)
```

App URLs are **path-based** (the directory name under `site/`), independent of the
repo name. Shared resources every app can link to:

- **Tech glossary:** https://public.suranku.com/learn/glossary.html (`site/learn/`)
- **Agents catalog:** https://public.suranku.com/agents/ (`site/agents/`)
- **Shared styles:** `site/assets/styles.css`

## Apps

| App | URL | Source |
| --- | --- | --- |
| Data Intelligence Portal | `/data-intelligence-portal/` | [`apps/data-intelligence-portal/`](apps/data-intelligence-portal/) |

## Two ways to run

The published site (GitHub Pages) is a **static showcase** — the apps run in browser-only
demo mode (authoring persists to `localStorage`; repo scanning and AI answers show a
"connect the backend" notice). For the **full experience** — scanning your own repos,
persistent metadata, and AI answers — run the FastAPI app, which **serves the site *and* the
API from one origin** (no CORS, no separate frontend hosting).

### Run the full app (Docker) — recommended

```bash
git clone https://github.com/Yamini-Suranku/suranku-public
cd suranku-public/apps/data-intelligence-portal
docker compose up --build      # full app at http://localhost:8080
```

That's the whole app — Build, **Scan Repo** (local folder, a public GitHub URL, a private
repo with your token, or an uploaded `.zip`), Lineage Graph, Monitoring, and the AI
Assistant. Optional env (set in `.env`, see `.env.example`): `ANTHROPIC_API_KEY` for Claude,
or point `OPENAI_BASE_URL` at a local Ollama/LM Studio server. Scanning a **private** repo
keeps your token on your machine.

### Host it (Render / Fly.io)

To stand up a live full instance (e.g. `app.suranku.com`) link to from the Pages hub:

- **AWS Lambda** (serverless, scale-to-zero — best for low/sporadic traffic): `sam deploy`
  with [`template.yaml`](template.yaml) → a Function URL serving site + API.
- **Render / Fly.io** (always-on container): [`render.yaml`](render.yaml) / [`fly.toml`](fly.toml).

All deploy the same app. See **[`DEPLOY.md`](DEPLOY.md)** for steps, env, persistence, and the
security guidance (don't accept private tokens on a shared instance).

## Add a new public app

1. **UI:** create `site/<app-id>/index.html`, reusing `/assets/` and `/learn/`.
2. **Backend (optional):** create `apps/<app-id>/` with `backend/`, `Dockerfile`,
   `requirements.txt`, and `tests/`. Self-hosting backends serve the shared site via the
   `PORTAL_SITE` env var (the Docker image copies `site/` to `/app/site`).
3. **Hub card:** add an `.app-card` for it in `site/index.html`.
4. **CI:** copy the `data-intelligence-portal` job in `.github/workflows/ci.yml` and point
   `working-directory` at `apps/<app-id>` (optionally add `paths:` filters).
5. **Optional:** add an entry to `site/agents/index.json` if it ships an agent.

## Deploy

`.github/workflows/pages.yml` publishes `site/` to GitHub Pages on every push to `main`;
`site/CNAME` sets the custom domain `public.suranku.com`. Each app's self-hosting
instructions live in its own README (e.g. [`apps/data-intelligence-portal/README.md`](apps/data-intelligence-portal/README.md)).

## License

Apache License 2.0 (see `LICENSE`). Suranku names and logos are not licensed under
Apache 2.0 — see `TRADEMARKS.md`.
