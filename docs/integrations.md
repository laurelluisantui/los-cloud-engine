# Integration architecture (Phase E)

The engine is the shared backend. Every integration authenticates as either a
human (Supabase JWT) or a scoped machine key, and touches only what its scopes
allow. Nothing here is claimed operational until its end-to-end test exists.

## 1. laurel-haven (Lovable app) — Muffy's primary surface

- **Direction**: app's chat panel → engine `POST /v1/chat` (SSE) with the
  owner's existing Supabase session token in `Authorization: Bearer`.
- **Engine side**: validates the token against the Lovable Cloud project's
  `auth/v1/user`, then confirms `user_roles = owner`. No new login, no password.
- **App side (Phase F)**: additive `MuffyPanel` component behind the
  `VITE_LOS_ENGINE_URL` flag; existing recommend-only Muffy functions stay
  untouched until the panel is verified.
- **Engine → app data**: future read tools call the app's existing authenticated
  public APIs (precedent: `/api/public/agent/assets` — bearer + RLS + audit
  log). The engine never gets the Lovable DB's service key.

## 2. YourTechCenter

No separate repo exists today (confirmed by owner). When it exists it consumes
the same documented APIs (`/openapi.json`) with its own scoped keys. Nothing to
preserve/migrate.

## 3. Laurel Companion (native Mac app)

- This is a future integration, not connected today. A scoped machine key can
  read agents/skills/tasks and submit explicitly authorized tasks. It **cannot**
  call owner-only `/v1/chat` or read Muffy's private memory. A future owner
  sign-in/token exchange is needed before `brainUrl` can carry Muffy chat.
- ⚠️ Its local config currently holds plaintext provider keys — rotate those
  and never commit them anywhere.

## 4. Notion

Read tools (future phase) use a Notion integration token stored ONLY in the
engine's host secrets (never given to agents). Scope: the L·OS SOP pages +
`LOS_Agent_Requests` queue. Writes require owner approval rows.

## 5. Google Drive

Agents receive Drive data only through laurel-haven's existing
owner-configured Drive pipeline (signed URLs from the app's authenticated
endpoints). The engine holds no Google credentials in v0.1.

## 6. CRM systems (Square today, others later)

Square data stays in laurel-haven. If agents need CRM facts, the engine calls
the app API (as with Drive). A direct CRM connector is a future, separately
approved step with read-only scopes first.

## 7. Future workers (cloud browser workers, Mac mini)

Pull model (design only): workers register, poll scoped work streams and post
results. Those worker APIs do not exist in v0.1; do not treat Mac mini or cloud
browser workers as operational.

## Endpoint summary (all authenticated except /healthz)

| Surface | Method/path | Scope |
|---|---|---|
| Chat (SSE) | `POST /v1/chat` | owner only |
| Memory | `GET /v1/conversations/{id}/messages` | owner only |
| Agents | `GET /v1/agents` | `agent.read` |
| Tasks | `POST /v1/tasks`, `GET /v1/tasks/{id}` | `task.create` / `task.read` |
| Runs | `GET /v1/runs` | `task.read` |
| Skills | `GET /v1/skills/{slug}`, `/versions` | `skill.read` |
| Skill edits | `POST /v1/skills/{slug}/propose`, `/rollback` | `skill.write`/`rollback` (+ approval) |
| Approvals | `GET /v1/approvals`, `POST /v1/approvals/{id}/decide` | owner only |
| Schedules | `POST /v1/schedules` (create/pause/resume/list) | `schedule.manage` |
| Costs | `GET /v1/costs` | `cost.read` |
| Events | `POST /v1/events/{name}` | `event.fire` |
| Machine keys | `POST /v1/keys` | owner only (shown once) |
