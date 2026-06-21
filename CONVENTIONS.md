# Public-app conventions (paths, hosting, adding an app)

This repo hosts **many public apps** under one scheme. Every app gets a **mandatory static
demo** (browser-only, no backend), an **optional live demo** (a backend running under
`app.suranku.com`), and a **"get the code"** link so anyone can self-host. This doc is the
contract that makes adding an app a repeatable recipe.

## The path scheme

Everything keys off one slug `<app-id>` (e.g. `data-intelligence-portal`), reused for the
static page, the backend, the repo folder, the Lambda stack, and the CloudFront behavior.

```
/                       hub — cards rendered from /apps.json
/assets/*               shared static assets (CSS/JS)
/<app-id>/              the app page = its demo (ALWAYS loads; browser-only capable)
/<app-id>/api/*         the app's live backend (only when it has one)
/<app-id>/api/health    liveness probe
```

Two hosts serve these:

| URL | Server | What you get |
| --- | --- | --- |
| `public.suranku.com/<app-id>/` | **GitHub Pages** | static demo — every app, no AWS dependency |
| `app.suranku.com/<app-id>/` | **CloudFront → static origin** | same page, upgrades to live if a backend exists |
| `app.suranku.com/<app-id>/api/*` | **CloudFront → that app's Lambda** | the live backend |

`site/` is the single source of truth for all static frontends. GitHub Pages is the canonical,
free static host and is **never** taken down — it's the durable "always works" guarantee.

## Static-vs-live is automatic (and degrades safely)

A page never assumes a backend is up. `site/assets/app.js` reads `<meta name="app-api-base">`
to build its API base, calls `…/api/health`, and on **any** failure (no backend, backend torn
down, network) **falls back to browser-only `staticApi()`** (localStorage). So:

- **Bringing a live demo down is safe** — the static demo still serves; the page just degrades.
- The same frontend code runs statically (Pages) and live (CloudFront → Lambda).

Set the meta to the app prefix when (and only when) the backend is mounted under it:
```html
<!-- single-app at origin root (today) -->        <meta name="app-api-base" content="">
<!-- multi-app, backend under the app prefix -->  <meta name="app-api-base" content="/<app-id>">
```

## The app registry — `site/apps.json`

The hub renders cards from this file; it's also the human checklist for "what exists."

```json
{
  "id": "data-intelligence-portal",
  "name": "Data Intelligence Portal",
  "category": "Data intelligence",
  "blurb": "One-line description.",
  "status": "live",                 // live | static-only | soon
  "page": "/data-intelligence-portal/",
  "api":  "/data-intelligence-portal/api",   // null when static-only
  "repo": "https://github.com/Yamini-Suranku/suranku-public/tree/main/apps/data-intelligence-portal"
}
```

`status` drives the card: `live` → "Live" badge + a "Live app ↗" link to `app.suranku.com`;
`static-only` → static badge, no live link; `soon` → placeholder, no demo link.

## Add an app (recipe)

1. **Static frontend:** create `site/<app-id>/` (an `index.html` + assets). Use **relative,
   app-prefixed** API calls via the `app-api-base` meta. The browser-only path must work with no
   backend (this is the mandatory static demo).
2. **Register it:** add an entry to `site/apps.json` (`status: "soon"` until it's ready). The hub
   card appears automatically — no HTML edit.
3. **"Get the code":** if self-hostable, create `apps/<app-id>/` with its own `README.md`
   (quickstart) + `docker-compose.yml` so `cd apps/<app-id> && docker compose up` just works.
   Point the registry `repo` at that subfolder.
4. **Live demo (optional):**
   - Backend serves `/<app-id>/api/*` (prefix-aware via `APP_BASE_PATH`); set the page's
     `app-api-base` meta to `/<app-id>`.
   - Deploy its Lambda as SAM stack `suranku-<app-id>` (mirror `template.yaml` /
     `Dockerfile.lambda`).
   - Add an origin + a `/<app-id>/api/*` behavior (AllViewerExceptHostHeader + CachingDisabled)
     to `infra/cloudfront-app.yaml`.
   - Flip the registry entry to `status: "live"`, `api: "/<app-id>/api"`.
5. **Bring a live demo down:** delete the app's SAM stack + remove its `/<app-id>/api/*`
   CloudFront behavior, and set the registry to `status: "static-only"`, `api: null`. The static
   demo (Pages + the static origin) is untouched.

## Hosting notes (status & roadmap)

- **Today (1 live app):** CloudFront's default origin is the single DIP Lambda (it still bundles
  `site/` and serves `/api` at root, so the DIP `app-api-base` meta is empty). Pages serves the
  static showcase independently.
- **At the 2nd live app (Phase 2):** move CloudFront's default origin to an **S3 bucket** holding
  the built `site/` (a mirror of what Pages serves — one build, two destinations), make each
  backend prefix-aware (`APP_BASE_PATH`, drop `COPY site/` from `Dockerfile.lambda`), and add
  per-app Lambda + `/<app-id>/api/*` behaviors. See `DEPLOY.md` and `infra/`.
