# AutoSMM AI

An autonomous SMM employee for local businesses: it interviews the owner, plans a
month of content, writes native Uzbek copy, renders the visuals, asks for approval
on Telegram, and publishes to Telegram channels and Instagram on schedule.

```
repo/
├── backend/          FastAPI + Celery + aiogram — the product (see backend/README.md)
└── src/, components/ React admin dashboard talking to that backend
```

The dashboard is a thin client: **all** data comes from the backend REST API.
There is no local mock state.

---

## Run the whole thing

### 1. Backend

```bash
cd backend
cp .env.example .env          # add GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, ENCRYPTION_KEY, API_KEY
docker compose up -d --build
docker compose exec api python scripts/seed.py --telegram-user-id <YOUR_TELEGRAM_ID>
```

Backend docs: <http://localhost:8000/docs> · full guide: [backend/README.md](backend/README.md)

### 2. Dashboard

```bash
npm install
cp .env.example .env          # AUTOSMM_API_KEY must match API_KEY in backend/.env
npm run dev                   # http://localhost:3000
```

---

## How the two connect

```
browser ──/api/v1/*──▶ Express (server.ts) ──+ X-API-Key──▶ FastAPI :8000
                       └── also proxies /media (rendered cards) and /health
```

`server.ts` injects `AUTOSMM_API_KEY` server-side, so the admin key never reaches
the browser and there are no CORS hops. Point the browser straight at the backend
instead by setting `VITE_API_URL` (and `VITE_API_KEY`) — then `CORS_ORIGINS` in
`backend/.env` has to include the dashboard origin.

| Variable | Where | Meaning |
|---|---|---|
| `BACKEND_URL` | dashboard `.env` | Backend origin the proxy forwards to |
| `AUTOSMM_API_KEY` | dashboard `.env` | Must equal `API_KEY` in `backend/.env` |
| `PORT` | dashboard `.env` | Dashboard port (default 3000) |
| `VITE_API_URL` | optional | Bypass the proxy and call the backend directly |

---

## What each screen does

| Screen | Backend endpoints | What you can do |
|---|---|---|
| **Overview** | `/analytics/summary`, `/items`, `/plans` | Live counters, pillar/format mix, the scheduled pipeline, bulk approve/reject, one-click approval of a pending weekly plan |
| **Businesses** | `/businesses`, `/businesses/{id}/knowledge`, `/credentials` | Create and toggle businesses, edit the knowledge base, paste free-form notes or upload a PDF (price list, brandbook) for the OnboardingAgent to structure, trigger a weekly plan |
| **Content Studio** | `/generate/item`, `/generate/plan`, `/items/*` | Ask the agents for a post (format, pillar, channel, topic, extra instructions), preview it as Telegram or Instagram, edit the caption, ask the AI to change something, approve / regenerate / publish now / reject |
| **Prompt Studio** | `/prompts`, `/prompts/defaults/{agent}` | Read every agent's built-in prompt, create scoped overrides (global or per business, optionally per pillar), version history and rollback |
| **Integrations** | `/businesses/{id}/credentials`, `/system/providers` | Store channel tokens (masked on read, encrypted at rest), live-test the connection, exchange a long-lived Instagram token, see which AI providers the backend has keys for |
| **System logs** | `/analytics/failures`, `/items/{id}/logs` | Failed publications with the reason, the per-attempt trail, export to JSON/CSV |

The dashboard re-reads the queue and the summary every 20 seconds, so posts appear
as the background workers finish them.

---

## Development

```bash
npm run dev         # Express + Vite with HMR
npm run typecheck   # tsc --noEmit
npm run build       # dist/ (SPA) + dist/server.cjs
npm start           # serve the production build
```

Backend quality gates live in `backend/`: `make test`, `make lint`, `make db-check`.
