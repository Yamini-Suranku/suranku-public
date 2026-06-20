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
