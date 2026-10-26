# L·OS Cloud Engine

L-OS Cloud Engine - AI agents, orchestration, and automation

Modular, cloud-hosted AI agent infrastructure for FORM + LOGIC / YourTechCenter.
Muffy — the owner-only executive orchestrator — is the primary natural-language
interface. This repo is the shared backend; it ships no frontend. Frontends
(laurel-haven / Lovable, Laurel Companion, future apps) consume it over
authenticated HTTPS APIs.

## Layout

- `engine/api/` — FastAPI app (chat SSE, tasks, runs, skills, schedules, approvals, costs, agents)
- `engine/agents/` — agent definitions (Muffy orchestrator, Sales Research Agent) — separate from skills
- `engine/skills_lib.py` — Git-backed Skills Library loader (versioned, rollback)
- `skills/` — Skills Library: SKILL.md + schema.json + version metadata + tests per skill
- `engine/worker.py` — task queue consumer: retries, timeouts, background jobs
- `engine/schedules.py` — cron-style schedules + event triggers
- `engine/models.py` + `db/migrations/` — org-scoped Postgres schema (Alembic)
- `tests/` — pytest: delegation, authorization, skill versioning, approvals, failure logging

## Auth model (confirmed with owner)

- Humans (laurel-haven chat panel): `Authorization: Bearer <Supabase access token>`.
  The engine validates it against the Supabase project's Auth API
  (`GET {SUPABASE_URL}/auth/v1/user`) and requires the `owner` role
  (`user_roles`, read via the service role key). No second login.
- Machine callers (schedulers, workers, Companion, Mac mini): `X-Engine-Key: <key>`
  scoped per organization. Client-facing surfaces never receive engine keys.
- Every privileged action is permission-checked in backend code before any tool runs.

## Local development (no Docker required)

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # fill in values; never commit .env
.venv/bin/alembic upgrade head
.venv/bin/uvicorn engine.api.app:create_app --factory --reload &
.venv/bin/python -m engine.worker &   # background task runner + scheduler tick
.venv/bin/pytest
```

SQLite is the local default (`ENGINE_DATABASE_URL=sqlite:///./dev.db`); Postgres is
used in deployment via `DATABASE_URL`. OpenAI calls require `OPENAI_API_KEY`;
without it the engine falls back to a deterministic dev provider so tests and
local demos run without spending money.

## Deployment (container, provider-portable)

```sh
docker build -t los-cloud-engine .
docker compose up         # api + worker + postgres
```

Set env vars per `.env.example`. Nothing vendor-specific: any container host
(Render, Fly.io, Cloud Run) works. CI (`.github/workflows/ci.yml`) runs pytest,
lint and the docker build. **Do not provision paid services without the
approved cost estimate.**

## Safety rules enforced in code

- Owner-only orchestration; per-organization isolation (`organization_id` on
  every table; RLS policies in Postgres deployments).
- Destructive / financial / publishing / external-communication actions require
  an explicit owner approval row before execution.
- Agents never get production credentials, unrestricted filesystem access, or
  raw outbound messaging. Muffy cannot fabricate status: status answers read
  `task_runs` only.
