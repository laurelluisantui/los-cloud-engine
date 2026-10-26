"""L·OS Cloud Engine API. AuthN/Z via auth.get_principal; humans use their
Supabase owner JWT, machines use scoped engine API keys."""
import json
import secrets
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, config, tools
from ..approvals import decide as decide_approval
from ..approvals import list_pending
from ..auth import ALL_PERMISSIONS, Principal, get_principal, hash_key
from ..db import get_session, engine as db_engine
from ..logging import configure, get_logger, new_request_id, principal_id
from ..models import ApiKey, Approval, Base
from ..muffy import ModelNotConfigured, get_or_create_conversation, run_muffy
from ..worker import fire_event

log = get_logger("los.api")


# ----------------------------------------------------------------- payloads --
class ChatIn(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    client_app: str = "laurel-haven"


class TaskIn(BaseModel):
    agent_slug: str
    input: Dict[str, Any] = {}
    skill_slug: Optional[str] = None
    timeout_seconds: int = Field(default=600, ge=1, le=3600)
    max_retries: int = Field(default=3, ge=1, le=10)


class SkillEditIn(BaseModel):
    new_version: str
    body: str
    reason: str = ""


class RollbackIn(BaseModel):
    to_version: str


class ApprovalDecisionIn(BaseModel):
    approve: bool


class ScheduleIn(BaseModel):
    action: str = "create"
    name: Optional[str] = None
    interval_seconds: int = 3600
    agent_slug: Optional[str] = None
    input: Dict[str, Any] = {}
    schedule_id: Optional[str] = None


class KeyIn(BaseModel):
    name: str
    scopes: List[str]


def create_app() -> FastAPI:
    configure()
    app = FastAPI(title="L·OS Cloud Engine", version="0.1.0")
    if config.ALLOWED_ORIGINS:
        app.add_middleware(
            CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS,
            allow_credentials=False, allow_methods=["GET", "POST"],
            allow_headers=["authorization", "content-type", "x-engine-key"],
        )

    @app.middleware("http")
    async def _ctx(request: Request, call_next):
        new_request_id()
        try:
            return await call_next(request)
        finally:
            principal_id.set("")

    @app.exception_handler(PermissionError)
    async def _perm(_, exc):
        return JSONResponse({"error": str(exc)}, status_code=403)

    @app.exception_handler(KeyError)
    async def _notfound(_, exc):
        return JSONResponse({"error": str(exc.args[0] if exc.args else "not found")},
                            status_code=404)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "service": "los-cloud-engine", "version": "0.1.0"}

    P = Depends(get_principal)
    S = Depends(get_session)

    # ------------------------------------------------------------- agents --
    @app.get("/v1/agents")
    def agents(principal: Principal = P, session: Session = S):
        return {"agents": tools.list_agents(session, principal)}

    # -------------------------------------------------------------- tasks --
    @app.post("/v1/tasks", status_code=201)
    def submit_task(body: TaskIn, principal: Principal = P, session: Session = S):
        try:
            task = tools.create_task(session, principal, body.agent_slug, body.input,
                                     skill_slug=body.skill_slug,
                                     timeout_seconds=body.timeout_seconds,
                                     max_retries=body.max_retries)
        except tools.PermissionDenied as exc:
            raise HTTPException(403, str(exc))
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0]))
        except Exception as exc:
            raise HTTPException(400, str(exc))
        return {"task_id": task.id, "status": task.status}

    @app.get("/v1/tasks/{task_id}")
    def get_task(task_id: str, principal: Principal = P, session: Session = S):
        try:
            return tools.task_status(session, principal, task_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0]))

    @app.get("/v1/runs")
    def runs(limit: int = 20, principal: Principal = P, session: Session = S):
        return {"runs": tools.run_history(session, principal, limit)}

    # ------------------------------------------------------------- skills --
    @app.get("/v1/skills/{slug}")
    def skill(slug: str, principal: Principal = P, session: Session = S):
        try:
            return tools.read_skill(session, principal, slug)
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0]))

    @app.get("/v1/skills/{slug}/versions")
    def versions(slug: str, principal: Principal = P, session: Session = S):
        return {"versions": tools.skill_versions(session, principal, slug)}

    @app.post("/v1/skills/{slug}/propose", status_code=202)
    def propose(slug: str, body: SkillEditIn, principal: Principal = P, session: Session = S):
        try:
            return tools.propose_skill_edit(session, principal, slug, body.body,
                                            body.new_version, body.reason)
        except tools.PermissionDenied as exc:
            raise HTTPException(403, str(exc))
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0]))
        except Exception as exc:
            raise HTTPException(400, str(exc))

    @app.post("/v1/skills/{slug}/rollback", status_code=202)
    def rollback(slug: str, body: RollbackIn, principal: Principal = P, session: Session = S):
        try:
            return tools.request_skill_rollback(session, principal, slug, body.to_version)
        except (KeyError,) as exc:
            raise HTTPException(404, str(exc.args[0]))
        except Exception as exc:
            raise HTTPException(400, str(exc))

    # ---------------------------------------------------------- approvals --
    @app.get("/v1/approvals")
    def approvals(principal: Principal = P, session: Session = S):
        if principal.kind != "owner":
            raise HTTPException(403, "Only the owner can view approvals")
        items = list_pending(session, principal.organization_id)
        return {"approvals": [
            {"id": a.id, "action": a.action, "requested_by": a.requested_by,
             "created_at": str(a.created_at),
             "summary": {k: v for k, v in a.payload.items() if k in ("slug", "version",
                         "to_version", "reason", "name")}} for a in items]}

    @app.post("/v1/approvals/{approval_id}/decide")
    def decide(approval_id: str, body: ApprovalDecisionIn,
               principal: Principal = P, session: Session = S):
        if principal.kind != "owner":
            raise HTTPException(403, "Only the owner can decide approvals")
        try:
            ap = decide_approval(session, principal.organization_id, approval_id,
                                 body.approve, principal.display or principal.id)
        except KeyError:
            raise HTTPException(404, "approval not found")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        result = None
        if body.approve:
            try:
                result = tools.execute_approved(session, principal, ap)
            except Exception as exc:
                session.rollback()
                ap = session.query(Approval).filter_by(id=approval_id, organization_id=principal.organization_id).one()
                ap.status = "failed"
                session.commit()
                audit.log(session, principal, "approval.failed", "approval", ap.id,
                          {"action": ap.action, "error": str(exc)[:500]})
                raise HTTPException(500, f"approved action failed: {exc}")
            ap.status = "approved"
            session.commit()
            if hasattr(result, "version"):
                result = {"published": {"slug": ap.payload.get("slug"),
                                        "version": getattr(result, "version", None)}}
        audit.log(session, principal,
                  "approval.approved" if body.approve else "approval.rejected",
                  "approval", ap.id, {"action": ap.action})
        return {"status": ap.status, "result": result}

    # ---------------------------------------------------------- schedules --
    @app.post("/v1/schedules", status_code=201)
    def schedules(body: ScheduleIn, principal: Principal = P, session: Session = S):
        try:
            return tools.manage_schedule(session, principal, body.action, body.name,
                                         body.interval_seconds, body.agent_slug,
                                         body.input, body.schedule_id)
        except tools.PermissionDenied as exc:
            raise HTTPException(403, str(exc))
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0]))
        except Exception as exc:
            raise HTTPException(400, str(exc))

    # --------------------------------------------------------------- cost --
    @app.get("/v1/costs")
    def costs(principal: Principal = P, session: Session = S):
        return tools.cost_report(session, principal)

    # ------------------------------------------------------------- events --
    @app.post("/v1/events/{event_name}", status_code=202)
    def event(event_name: str, payload: Dict[str, Any] = {},
              principal: Principal = P, session: Session = S):
        if not principal.can("event.fire"):
            raise HTTPException(403, "Missing permission: event.fire")
        n = fire_event(session, principal.organization_id, event_name, payload)
        audit.log(session, principal, "event.fire", "event", event_name, {"enqueued": n})
        return {"enqueued": n}

    # ---------------------------------------------------------------- keys --
    @app.post("/v1/keys", status_code=201)
    def mint_key(body: KeyIn, principal: Principal = P, session: Session = S):
        if principal.kind != "owner":
            raise HTTPException(403, "Only the owner can mint machine keys")
        bad = [s for s in body.scopes if s not in ALL_PERMISSIONS]
        if bad:
            raise HTTPException(400, f"unknown scopes: {bad}")
        if "approval.decide" in body.scopes:
            raise HTTPException(400, "machine keys cannot decide approvals")
        raw = "losk_" + secrets.token_urlsafe(24)
        row = ApiKey(organization_id=principal.organization_id, name=body.name,
                     key_hash=hash_key(raw), scopes=body.scopes)
        session.add(row)
        session.commit()
        audit.log(session, principal, "key.mint", "api_key", row.id,
                  {"name": body.name, "scopes": body.scopes})
        return {"key": raw, "name": body.name, "scopes": body.scopes,
                "note": "Store this now; it is shown once."}

    # ---------------------------------------------------------------- chat --
    @app.post("/v1/chat")
    def chat(body: ChatIn, request: Request, principal: Principal = P, session: Session = S):
        if principal.kind != "owner":
            raise HTTPException(403, "Muffy is owner-only")
        conv = get_or_create_conversation(session, principal, body.conversation_id,
                                          body.client_app)

        async def stream():
            try:
                async for evt in run_muffy(session, principal, conv, body.message):
                    yield f"data: {json.dumps(evt, default=str)}\n\n"
            except ModelNotConfigured as exc:
                yield f"data: {json.dumps({'type': 'error', 'data': str(exc)})}\n\n"
            except Exception as exc:  # noqa: BLE001
                log.exception("chat stream failed")
                yield f"data: {json.dumps({'type': 'error', 'data': f'chat failed: {exc}'})}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store"})

    @app.get("/v1/conversations/{conversation_id}/messages")
    def messages(conversation_id: str, principal: Principal = P, session: Session = S):
        from ..models import Conversation, Message
        if principal.kind != "owner":
            raise HTTPException(403, "Muffy is owner-only")
        conv = (session.query(Conversation)
                .filter_by(id=conversation_id, organization_id=principal.organization_id)
                .one_or_none())
        if conv is None or conv.owner_user_id != principal.id:
            raise HTTPException(404, "conversation not found")
        rows = (session.query(Message).filter_by(conversation_id=conv.id)
                .order_by(Message.created_at.asc()).all())
        return {"messages": [{"role": m.role, "content": m.content,
                              "tool_events": m.tool_events,
                              "created_at": str(m.created_at)} for m in rows]}

    return app


app = create_app()
