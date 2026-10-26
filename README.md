# L·OS Cloud Engine

L-OS Cloud Engine - AI agents, orchestration, and automation

Modular, cloud-hosted AI agent infrastructure for FORM + LOGIC / YourTechCenter.
Muffy — the owner-only executive orchestrator — is the primary natural-language
interface. This repo is the shared backend; it ships no frontend. Frontends
(laurel-haven / Lovable, Laurel Companion, future apps) consume it over
authenticated HTTPS APIs.

## Layout

- `engine/api/` — FastAPI app (chat SSE, tasks, runs, skills, schedules, approvals, costs, agents)
- `engine/muffy.py` and `engine/seed.py` — orchestrator and agent registry, separate from skills
- `engine/skills_lib.py` — repository-tracked skill definitions and database versions
- `skills/` — Skills Library: SKILL.md + schema.json + version metadata + tests per skill
- `engine/worker.py` — task queue consumer: retries, timeouts, background jobs
- `engine/worker.py` — interval schedules and event-triggered jobs
- `engine/models.py` + `db/migrations/` — org-scoped Postgres schema (Alembic)
- `tests/` — pytest: delegation, authorization, skill versioning, approvals, failure logging

## Auth model (confirmed with owner)

- Humans (laurel-haven chat panel): `Authorization: Bearer <Supabase access token>`.
  The engine validates it against the Supabase project's Auth API
  (`GET {SUPABASE_URL}/auth/v1/user`) and requires the `owner` role
  (`user_roles`, read with that user's own JWT under RLS). No service key
  or second login.
- Machine callers (schedulers, workers, Companion, Mac mini): `X-Engine-Key: <key>`
  scoped per organization. Client-facing surfaces never receive engine keys.
- Every privileged action is permission-checked in backend code before any tool runs.

## Local development (no Docker required)

Use Python 3.12 for Muffy's OpenAI Agents SDK (the host Mac's system Python
3.9 can run most tests, but cannot import the current SDK).

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/alembic upgrade head
.venv/bin/python -m engine.seed
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
cp .env.example .env   # set two strong DB passwords; never commit .env
docker compose up --build  # api + worker + Postgres
```

Set env vars per `.env.example`. Nothing vendor-specific: any container host
(Render, Fly.io, Cloud Run) works. CI (`.github/workflows/ci.yml`) runs pytest
and builds both images. **Do not provision paid services without the
approved cost estimate.**

## Remaining launch gates

- PostgreSQL RLS has not been exercised against a real Postgres instance on this
  Mac (no Docker or `psql` installed). Never connect the engine as `postgres`
  or a Supabase `service_role`: both can bypass tenant policies.
- On Postgres, an approved skill publish requires a narrow GitHub credential
  (`ENGINE_GITHUB_TOKEN`) and checks the remote SHA/content before updating
  `SKILL.md`. Its real GitHub integration has only mock tests; verify it in
  staging before allowing owner skill writes. Git and DB cannot commit in one
  transaction, so a post-Git DB error requires manual reconciliation.
- Muffy's live OpenAI chat, browser CORS, Lovable owner JWTs, and non-owner
  denial must be tested against actual staging endpoints before publishing the UI.

## Safety rules enforced in code

- Owner-only orchestration; tenant-scoped API queries and fail-closed Postgres
  policies for tenant tables (owner-only conversation/message policies).
- Destructive / financial / publishing / external-communication actions require
  an explicit owner approval row before execution.
- Agents never get production credentials, unrestricted filesystem access, or
  raw outbound messaging. Muffy cannot fabricate status: status answers read
  `task_runs` only.
