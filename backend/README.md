# AutoSMM AI — Autonomous SMM Employee

An AI system that runs social media for a local business end to end: it interviews
the owner, plans a month of content, writes native Uzbek copy, renders the visuals,
asks for approval on Telegram, and publishes to Telegram channels and Instagram on
schedule.

Optimised for **education centres** (o'quv markazlar), but every vertical-specific
detail lives in the knowledge base, not in the code.

```
Owner (Telegram)                    AutoSMM AI                          Audience
──────────────────                  ──────────                          ────────
"IELTS 600 ming" ──voice/text──▶ OnboardingAgent ──▶ KnowledgeBase
                                        │
                            weekly ─────▶ StrategistAgent   30% sales · 30% edu
                                        │                    25% proof · 15% quiz
                                        ▼
                                  CopywriterAgent ──▶ TG + IG captions
                                        │
                                  VisualAgent ──────▶ Flux photo / HTML card
                                        │
                                  EditorAgent ──────▶ score, fixes, guardrails
                                        ▼
  [✅ Tasdiqlash] [✏️ Tahrirlash] [🔄 Qayta yaratish]  ◀── approval stream
                                        │
                                  Celery Beat (60s) ──▶ Telegram channel
                                                        Instagram feed/carousel/story
```

---

## Table of contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Quick start (Docker)](#quick-start-docker)
4. [Local development](#local-development)
5. [Configuration](#configuration)
6. [Using the system](#using-the-system)
7. [REST API](#rest-api)
8. [The agents](#the-agents)
9. [Scheduling and publishing](#scheduling-and-publishing)
10. [Testing](#testing)
11. [Operations](#operations)
12. [Project layout](#project-layout)

---

## Features

**Multi-agent content engine**
- `OnboardingAgent` — interviews the owner (text *or* voice) and keeps a structured knowledge base.
- `StrategistAgent` — produces a dated content matrix with a strictly enforced pillar mix.
- `CopywriterAgent` — native Uzbek copy for Telegram (HTML) and Instagram, with CTA and hashtags.
- `VisualAgent` — writes English Flux.1 prompts and renders HTML/CSS cards to PNG (stories, carousels).
- `EditorAgent` — deterministic rules + LLM self-reflection; triggers a rewrite when quality is low.

**Telegram approval bot (aiogram 3)**
- Every post arrives as a card with `[✅ Tasdiqlash] [✏️ Tahrirlash] [🔄 Qayta yaratish]`.
- Voice feedback: say *«Dushanbadagi narxni 400 ming qil»* and the post is rewritten and re-sent.
- One-click weekly batch approval for the whole plan.

**Automated publishing**
- Beat heartbeat every 60 seconds picks up approved items whose time has come.
- Telegram: photos, albums, quizzes/polls, long-caption splitting.
- Instagram Graph API: single image, carousel (2–10), stories, with container polling.
- Retries with backoff, token-expiry detection, per-attempt audit log, admin alerts.

**Production concerns handled**
- Async SQLAlchemy 2.0 + Alembic; `FOR UPDATE SKIP LOCKED` so workers never double-post.
- Channel tokens encrypted at rest (Fernet) and masked in API responses.
- Structured logging, typed error hierarchy, retry/timeout policy on every provider call.
- Graceful degradation: no Flux key → designed card; no Chromium → Pillow card; no broker → inline run.

---

## Architecture

| Component | Technology | Role |
|---|---|---|
| API | FastAPI + Uvicorn | CRUD, triggers, analytics, media host, webhook |
| Database | PostgreSQL 16 | Businesses, knowledge, plans, items, logs |
| Cache / broker | Redis 7 | Celery broker + bot FSM storage |
| Queue | Celery + Beat | Generation, publishing, maintenance |
| Bot | aiogram 3 | Approval workflow, onboarding, voice feedback |
| LLM | Gemini 1.5 Flash / Pro | Planning, copy, review, transcription fallback |
| Images | Flux.1 Schnell (fal.ai / Replicate) | Photographic feed images |
| Rendering | Playwright + Jinja2 (Pillow fallback) | Story and carousel cards |
| Voice | OpenAI Whisper (Gemini fallback) | Owner voice notes |

Queues are separated on purpose: `generation` is LLM-bound with long timeouts and
low concurrency, `publishing` is IO-bound, short and highly concurrent.

---

## Quick start (Docker)

```bash
cd backend
cp .env.example .env

# Generate the encryption key and paste it into .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Fill in at minimum: GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, ENCRYPTION_KEY, API_KEY

docker compose up -d --build
docker compose exec api python scripts/seed.py --telegram-user-id <YOUR_TELEGRAM_ID>
```

Then:

- API docs → <http://localhost:8000/docs>
- Health → <http://localhost:8000/health/ready>
- Celery UI → `docker compose --profile monitoring up -d flower` → <http://localhost:5555>
- Open your bot in Telegram and send `/start`.

Migrations run automatically in the one-shot `migrate` service before the app
containers start.

> **Instagram needs a public URL.** Meta downloads your images over the internet,
> so `PUBLIC_BASE_URL` must be reachable from outside. For local testing:
> `cloudflared tunnel --url http://localhost:8000` and paste the HTTPS URL into `.env`.

> **Ports already taken?** Set `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`,
> `API_HOST_PORT` or `FLOWER_HOST_PORT` in `.env` — only the host side of the
> mapping changes, the containers keep talking to each other on the defaults.

---

## Local development

```bash
make venv          # virtualenv + dev dependencies
make browsers      # Chromium for the card renderer (optional; Pillow is the fallback)
cp .env.example .env

docker compose up -d postgres redis
make migrate
make seed

make api           # http://localhost:8000/docs
make worker        # in another shell
make beat          # in a third shell
make bot           # in a fourth shell
```

Quality gates:

```bash
make test          # pytest
make cov           # coverage report
make lint          # ruff
make db-check      # models vs migrations drift check
```

---

## Configuration

Everything comes from the environment — see [`.env.example`](.env.example) for the
annotated list. The essentials:

| Variable | Required | Notes |
|---|---|---|
| `GEMINI_API_KEY` | yes | All text generation and planning |
| `TELEGRAM_BOT_TOKEN` | yes | The system bot used for approvals |
| `ENCRYPTION_KEY` | recommended | Fernet key; derived from `SECRET_KEY` when empty |
| `API_KEY` | yes in prod | Sent by the dashboard as `X-API-Key` |
| `PUBLIC_BASE_URL` | yes for Instagram | Must be publicly reachable HTTPS |
| `FAL_API_KEY` / `REPLICATE_API_TOKEN` | optional | Without it, feed posts use rendered cards |
| `OPENAI_API_KEY` | optional | Whisper; Gemini transcribes audio otherwise |
| `META_APP_ID` / `META_APP_SECRET` | optional | Needed only for long-lived token refresh |
| `AUTO_APPROVE` | no | `true` publishes without human review (not recommended) |

Per-business overrides live in `businesses.settings`:

```json
{ "posts_per_week": 10, "posting_hours": [9, 13, 18], "auto_approve": false }
```

---

## Using the system

### 1. Create a business

Either `POST /api/v1/businesses`, or simply send `/start` to the bot — the first
message creates the business and registers you as its owner.

### 2. Fill the knowledge base

The bot asks six questions (offerings, prices, USPs, social proof, FAQ, contacts).
Answer by text **or voice note**. Anything you send outside a flow is also parsed
and merged in, so the profile keeps improving. `/kb` shows progress.

**PDF ingest** — send the bot a PDF (price list, brochure, brandbook) or upload
one on the dashboard's knowledge sheet; the document goes to the model as-is
(scans work too) and the extracted facts are merged into the knowledge base.
When the active `LLM_PROVIDER` cannot read documents, the call falls back to
Gemini — so a Groq-first deployment still needs `GEMINI_API_KEY` for this.

Programmatic equivalents: `PUT /api/v1/businesses/{id}/knowledge` (structured),
`POST /api/v1/businesses/{id}/knowledge/ingest` (free-form text → structured) or
`POST /api/v1/businesses/{id}/knowledge/ingest-file` (multipart PDF/text upload,
12 MB max).

### 3. Generate a plan

`/plan` in the bot, or:

```bash
curl -X POST http://localhost:8000/api/v1/generate/plan \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"business_id":"<uuid>","horizon_days":7,"posts_count":10}'
```

You receive a summary card with the pillar breakdown plus the first posts to review.

### 4. Review

| Button | Effect |
|---|---|
| ✅ Tasdiqlash | Approves; publishes automatically at `scheduled_at` |
| ✏️ Tahrirlash | Prompts for an instruction — typed or spoken — then rewrites |
| 🔄 Qayta yaratish | Regenerates copy **and** image from scratch |
| 🕐 Vaqtni o'zgartirish | Reschedules (`18:00` or `25.08.2026 18:00`) |
| 🗑 Bekor qilish | Rejects the post |

Voice instructions are transcribed, classified into an intent
(`change_price`, `reschedule`, `regenerate`, `reject`, …) and applied.

### 5. Publishing

Approved items go out by themselves. `/status` shows the queue; the dashboard shows
per-item logs at `GET /api/v1/items/{id}/logs`.

---

## REST API

Base path `/api/v1`. Every request needs `X-API-Key` (relaxed in development).
All responses share one envelope:

```json
{ "success": true, "data": {}, "error": null, "meta": {"total": 0, "page": 1, "limit": 20} }
```

| Method | Path | Purpose |
|---|---|---|
| `GET/POST` | `/businesses` | List / create businesses |
| `GET/PATCH/DELETE` | `/businesses/{id}` | Read, update, delete |
| `GET/PUT` | `/businesses/{id}/credentials` | Channel tokens (masked on read) |
| `POST` | `/businesses/{id}/credentials/verify` | Live check of the stored tokens |
| `POST` | `/businesses/{id}/credentials/refresh-token` | Long-lived Instagram token exchange |
| `GET/PUT` | `/businesses/{id}/knowledge` | Knowledge base |
| `POST` | `/businesses/{id}/knowledge/ingest` | Free-form text → structured facts |
| `POST` | `/businesses/{id}/knowledge/ingest-file` | Uploaded PDF / text file → structured facts |
| `GET/POST/DELETE` | `/businesses/{id}/admins` | Telegram reviewers |
| `GET` | `/plans`, `/plans/{id}` | Content plans (detail includes items) |
| `POST` | `/plans/{id}/approve` | One-click approve the whole plan |
| `GET/POST` | `/items` | Content queue with filters |
| `PATCH` | `/items/{id}` | Edit a pending item |
| `POST` | `/items/{id}/approve`, `/reject` | Review decisions |
| `POST` | `/items/bulk-status` | Batch approve / reject |
| `GET` | `/items/{id}/logs` | Publication attempt history |
| `POST` | `/generate/plan`, `/generate/item` | Trigger generation |
| `POST` | `/generate/item/{id}/regenerate` | Rewrite with an instruction |
| `POST` | `/generate/item/{id}/publish` | Publish immediately |
| `GET` | `/generate/task/{task_id}` | Celery task state |
| `GET/POST/PATCH/DELETE` | `/prompts` | Prompt Studio (versioned, rollback-able) |
| `GET` | `/analytics/summary`, `/analytics/business/{id}` | Dashboard metrics |
| `GET` | `/system/providers` | Which integrations are configured |

Unversioned: `GET /health`, `GET /health/ready`, `POST /telegram/webhook`, `GET /media/*`.

---

## The agents

### Pillar distribution — enforced, not suggested

`StrategistAgent` computes the exact per-pillar counts with a largest-remainder
split before the LLM is called, then repairs the LLM's answer against it:

| Pillar | Share | 10 posts |
|---|---|---|
| Sales | 30% | 3 |
| Educational | 30% | 3 |
| Social proof | 25% | 3 |
| Interactive | 15% | 1 |

The counts always sum to the requested total, and no pillar is dropped. If the
model fails entirely, a deterministic blueprint is used — a business never ends up
without a plan.

### Editor guardrails

Deterministic checks run first and cannot be talked out of by the model: empty
copy, unfilled placeholders (`[narx]`, `{{name}}`), robotic phrases, missing CTA
or contact details, banned topics, platform length limits, duplicate hashtags,
carousel slide counts, quiz answer-index sanity. The LLM pass adds language-level
findings and may rewrite the captions. Score `< 7.0` or any `critical` issue
triggers one targeted rewrite before the item is offered for review.

### Prompt Studio

Every agent resolves its system prompt through the database first:
`(business, pillar)` → `(business, *)` → `(global, pillar)` → built-in default.
Editing a prompt snapshots the previous version, and `POST /prompts/{id}/rollback/{n}`
restores it — prompts are tuned without a deploy.

---

## Scheduling and publishing

| Schedule | Task | Purpose |
|---|---|---|
| every 60s | `publishing.publish_due_content` | Publish approved, due items |
| every 15m | `publishing.retry_failed` | Re-queue transient failures |
| every 10m | `generation.send_pending_reviews` | Deliver undelivered review cards |
| Sat 10:00 | `generation.generate_plans_for_all` | Next week's plan for every business |
| daily 03:30 | `maintenance.cleanup_media` | Media retention |
| every 30m | `maintenance.unstick_stale_items` | Recover items abandoned by a crashed worker |

Content type → channel mapping:

| Type | Telegram | Instagram |
|---|---|---|
| `feed_post` | photo + caption | feed image |
| `carousel` | media group | carousel (2–10) |
| `story` | photo | story |
| `telegram_quiz` | native quiz poll | — |
| `reels_script` | formatted shot list | — |

Times are stored in UTC and rendered in the business timezone (`Asia/Tashkent`
by default), so `18:00` in the bot means 18:00 for the audience.

---

## Testing

```bash
make test                                   # everything
.venv/bin/python -m pytest -m "not db"      # unit only, no database needed
make cov                                    # coverage report
```

`pytest.ini` points the suite at `localhost:55432` by default; override with
`POSTGRES_HOST` / `POSTGRES_PORT`, or start the compose database and point at it.

Tests are split into pure unit tests (helpers, pillar maths, editor rules,
schema conversion), provider tests against a mocked HTTP transport (Gemini finish
reasons, token limits, retry policy, Telegram/Instagram payloads and error
classification), a full pipeline test with a stubbed LLM that asserts the real
distribution, scheduling and PNG rendering, and API tests against a real
PostgreSQL instance. DB-backed tests skip automatically when Postgres is absent.

---

## Operations

**Instagram token expiry** — `verify` reports it, `refresh-token` exchanges a
long-lived token (needs `META_APP_ID`/`META_APP_SECRET`). The publisher flags
`token_expired` and stops retrying rather than burning the rate limit.

**Rate limits** — Instagram allows 25 posts per account per rolling 24h;
`GET /businesses/{id}/credentials/verify` returns the remaining quota.

**Cost** — every generation records tokens and estimated USD in `content_items.ai_meta`;
`/analytics/summary` aggregates it.

**Failure alerts** — once an item exceeds `MAX_PUBLISH_RETRIES` the owner is
notified on Telegram with the error, and the attempt trail is in `publish_logs`.

---

## Project layout

```
backend/
├── app/
│   ├── agents/          # onboarding, strategist, copywriter, visual, editor,
│   │                    # feedback, orchestrator (the pipeline), prompts
│   ├── api/             # FastAPI routers, dependencies, envelope
│   ├── bot/             # aiogram routers, keyboards, FSM, review presenter
│   ├── core/            # settings, logging, errors, encryption
│   ├── db/              # declarative base, async session factory
│   ├── models/          # SQLAlchemy models + enums
│   ├── repositories/    # all SQL lives here
│   ├── schemas/         # Pydantic v2 contracts (API *and* LLM output)
│   ├── services/        # Gemini, Flux, Whisper, renderer, storage, publishers
│   ├── tasks/           # Celery app, beat schedule, workers
│   ├── templates/       # HTML/CSS card templates
│   └── utils/           # text, dates, JSON/schema helpers
├── alembic/             # migrations
├── scripts/             # seed data, container entrypoint
├── tests/
├── docker-compose.yml
├── Dockerfile
└── Makefile
```

---

## License

Proprietary — © AutoSMM AI.
