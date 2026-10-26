# Deployment

**Rule: no paid service is provisioned without an approved cost estimate
(see `docs/costs.md`).**

## Targets

The engine is a plain container + Postgres. It runs identically on Render,
Fly.io, GCP Cloud Run, or any VM with Docker. First target: **Render**
(web service + background worker, starter tier).

## One-time setup

1. The private GitHub repo `laurelluisantui/los-cloud-engine` already exists.
   After explicit cost/service approval, create a dedicated Supabase project.
   Record a Postgres connection string for a **non-superuser, non-BYPASSRLS**
   app role, with CREATE privileges on its own schema. Do not use the
   Supabase `service_role` or `postgres` role for application traffic.
2. Provision hosting ONLY after cost approval:
   - Web service: `alembic upgrade head && python -m engine.seed && uvicorn
     engine.api.app:create_app --factory --host 0.0.0.0 --port $PORT`
   - Background worker: `python -m engine.worker`
   - Health check: `GET /healthz`
3. Set environment variables (see `.env.example`):
   - `ENGINE_DATABASE_URL` — dedicated engine Postgres URI (app role)
   - `OPENAI_API_KEY`, `MUFFY_MODEL`, `ENGINE_MODEL`
   - `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
     (the *laurel-haven Lovable Cloud* project — used to validate owner JWTs)
   - `ENGINE_INTERNAL_SECRET` — generate a random 32+ char value
   - `ENGINE_ALLOWED_ORIGINS` — exact Lovable owner site origin; no wildcard
4. `alembic upgrade head` applies RLS automatically on Postgres; verify
   cross-tenant reads and writes are denied with an unset/wrong org context.
5. In laurel-haven, set the engine base URL env var (used by the Muffy panel)
   and keep the panel behind its config flag until verified.

## Portability

- All configuration is env vars; no hostnames, IPs, or credentials in code.
- The DB layer is SQLAlchemy-only; sqlite for dev, Postgres for prod.
- CI builds the images on every push; re-targeting hosts = changing the
  deploy destination, not the code.

## Rollback

- Application: redeploy the previous image tag.
- Database: test `alembic downgrade -1` on staging before any production
  rollback (downgrading RLS removes isolation, so NEVER run live unreviewed).
- Skill content: `skill.rollback` is approval-gated; durable GitHub sync is
  not yet operational.

## Security checklist (every deploy)

- [ ] `OPENAI_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY` set only as host secrets — never in the repo
- [ ] RLS migration applied and exercised on real Postgres as a non-bypass role
- [ ] Owner JWT flow verified: non-owner token → 403 on `/v1/chat`
- [ ] Machine keys minted per-caller with minimal scopes; never the `approval.decide` scope
- [ ] `GET /healthz` public; everything else authenticated
- [ ] HTTPS only (host-managed TLS)
- [ ] DNS-rebinding resistant egress policy or outbound proxy restricts agent
      website fetches to public hosts; application-level checks alone are insufficient
