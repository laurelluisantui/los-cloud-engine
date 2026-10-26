# Deployment

**Rule: no paid service is provisioned without an approved cost estimate
(see `docs/costs.md`).**

## Targets

The engine is a plain container + Postgres. It runs identically on Render,
Fly.io, GCP Cloud Run, or any VM with Docker. First target: **Render**
(web service + background worker, starter tier).

## One-time setup

1. Create the Supabase project `los-cloud-engine` in Laurel's personal org
   (free tier is enough for dev). Note the Postgres connection string.
2. Create the GitHub repo `laurelluisantui/los-cloud-engine` (private) and push.
3. Provision hosting ONLY after cost approval:
   - Web service: `alembic upgrade head && python -m engine.seed && uvicorn
     engine.api.app:create_app --factory --host 0.0.0.0 --port $PORT`
   - Background worker: `python -m engine.worker`
   - Health check: `GET /healthz`
4. Set environment variables (see `.env.example`):
   - `ENGINE_DATABASE_URL` — Supabase Postgres URI
   - `OPENAI_API_KEY`, `MUFFY_MODEL`, `ENGINE_MODEL`
   - `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
     (the *laurel-haven Lovable Cloud* project — used to validate owner JWTs)
   - `ENGINE_INTERNAL_SECRET` — generate a random 32+ char value
5. Apply RLS once on the database: `psql "$ENGINE_DATABASE_URL" -f db/migrations/0002_rls.sql`.
6. In laurel-haven, set the engine base URL env var (used by the Muffy panel)
   and keep the panel behind its config flag until verified.

## Portability

- All configuration is env vars; no hostnames, IPs, or credentials in code.
- The DB layer is SQLAlchemy-only; sqlite for dev, Postgres for prod.
- CI builds the images on every push; re-targeting hosts = changing the
  deploy destination, not the code.

## Rollback

- Application: redeploy the previous image tag.
- Database: `alembic downgrade -1` (migrations are reversible; RLS file is idempotent).
- Skill content: Muffy/API `skill.rollback` restores exact prior bytes (approval-gated).

## Security checklist (every deploy)

- [ ] `OPENAI_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY` set only as host secrets — never in the repo
- [ ] RLS policies applied (`0002_rls.sql`) on Postgres
- [ ] Owner JWT flow verified: non-owner token → 403 on `/v1/chat`
- [ ] Machine keys minted per-caller with minimal scopes; never the `approval.decide` scope
- [ ] `GET /healthz` public; everything else authenticated
- [ ] HTTPS only (host-managed TLS)
