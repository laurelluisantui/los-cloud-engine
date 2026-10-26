"""Service layer used by BOTH the REST API and Muffy's orchestration tools.
Permission checks happen here, in code, before anything executes."""
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from . import audit, providers
from .approvals import create_approval, requires_approval
from .auth import Principal
from .models import Agent, Schedule, Skill, Task, TaskRun, utcnow
from .skills_lib import (SkillDef, SkillError, active_version, load_skill_dir,
                         publish, rollback, run_skill, skill_impl, validate, versions)


class PermissionDenied(Exception):
    pass


def _need(principal: Principal, perm: str) -> None:
    if not principal.can(perm):
        raise PermissionDenied(f"missing permission: {perm}")


# Dev-mode sample page so proposals never need the network without a model key.
_SAMPLE_PAGE = ("<html><head><title>Example Studio — Design & Build</title>"
                "<meta name='description' content='Example Studio builds brands and sites.'>"
                "</head><body><p>Example Studio serves clients in Houston.</p></body></html>")


def _sample_fetch(provider):
    if getattr(provider, "name", "dev") == "dev":
        return lambda url, timeout=15.0: _SAMPLE_PAGE
    from .runtime import bounded_fetch
    return bounded_fetch
def list_agents(session: Session, principal: Principal) -> List[Dict[str, Any]]:
    _need(principal, "agent.read")
    rows = (session.query(Agent)
            .filter_by(organization_id=principal.organization_id, status="active").all())
    return [{"slug": a.slug, "name": a.name, "kind": a.kind, "description": a.description,
             "skills": a.skills, "permissions": a.permissions} for a in rows]


def register_agent(session: Session, principal: Principal, slug: str, name: str,
                   kind: str, description: str, skills: List[str],
                   permissions: List[str]) -> Agent:
    _need(principal, "agent.manage")
    a = Agent(organization_id=principal.organization_id, slug=slug, name=name,
              kind=kind, description=description, skills=skills, permissions=permissions)
    session.add(a)
    session.commit()
    session.refresh(a)
    audit.log(session, principal, "agent.register", "agent", a.id, {"slug": slug})
    return a


# ------------------------------------------------------------------- tasks --
def create_task(session: Session, principal: Principal, agent_slug: str,
                input_data: Dict[str, Any], skill_slug: Optional[str] = None,
                conversation_id: Optional[str] = None,
                timeout_seconds: int = 600, max_retries: int = 3) -> Task:
    _need(principal, "task.create")
    agent = (session.query(Agent)
             .filter_by(organization_id=principal.organization_id, slug=agent_slug,
                        status="active").one_or_none())
    if agent is None:
        raise KeyError(f"unknown agent '{agent_slug}'")
    skill = skill_slug or (agent.skills[0] if agent.skills else None)
    if skill is None:
        raise SkillError(f"agent '{agent_slug}' has no skills")
    if skill not in agent.skills:
        raise PermissionDenied(f"agent '{agent_slug}' is not allowed skill '{skill}'")
    task = Task(organization_id=principal.organization_id, agent_id=agent.id,
                skill_slug=skill, input=input_data, status="queued",
                timeout_seconds=timeout_seconds, max_retries=max_retries,
                conversation_id=conversation_id, created_by=principal.display or principal.id)
    session.add(task)
    session.commit()
    session.refresh(task)
    audit.log(session, principal, "task.create", "task", task.id,
              {"agent": agent_slug, "skill": skill})
    return task


def task_status(session: Session, principal: Principal, task_id: str) -> Dict[str, Any]:
    _need(principal, "task.read")
    t = (session.query(Task)
         .filter_by(id=task_id, organization_id=principal.organization_id).one_or_none())
    if t is None:
        raise KeyError("task not found")
    runs = (session.query(TaskRun).filter_by(task_id=t.id)
            .order_by(TaskRun.started_at.desc()).all())
    return {
        "id": t.id, "status": t.status, "agent": t.agent_id, "skill": t.skill_slug,
        "attempts": t.attempts, "created_by": t.created_by,
        "runs": [{"id": r.id, "attempt": r.attempt, "status": r.status,
                  "error": r.error, "cost_usd": r.cost_usd,
                  "skill_version": r.skill_version,
                  "started_at": str(r.started_at), "finished_at": str(r.finished_at)}
                 for r in runs],
    }


def run_history(session: Session, principal: Principal, limit: int = 20) -> List[Dict[str, Any]]:
    _need(principal, "task.read")
    runs = (session.query(TaskRun)
            .filter_by(organization_id=principal.organization_id)
            .order_by(TaskRun.started_at.desc()).limit(limit).all())
    return [{"task_id": r.task_id, "status": r.status, "attempt": r.attempt,
             "error": r.error, "cost_usd": r.cost_usd, "skill_version": r.skill_version,
             "started_at": str(r.started_at)} for r in runs]


# ------------------------------------------------------------------ skills --
def read_skill(session: Session, principal: Principal, slug: str) -> Dict[str, Any]:
    _need(principal, "skill.read")
    sv = active_version(session, principal.organization_id, slug)
    if sv is None:
        raise KeyError(f"skill '{slug}' not published")
    return {"slug": slug, "version": sv.version, "content_hash": sv.content_hash,
            "body": sv.body, "schema_input": sv.schema_input, "schema_output": sv.schema_output}


def skill_versions(session: Session, principal: Principal, slug: str) -> List[Dict[str, Any]]:
    _need(principal, "skill.read")
    return [{"version": v.version, "status": v.status, "hash": v.content_hash,
             "created_by": v.created_by, "created_at": str(v.created_at)}
            for v in versions(session, principal.organization_id, slug)]


def propose_skill_edit(session: Session, principal: Principal, slug: str,
                       new_body: str, new_version: str,
                       reason: str = "") -> Dict[str, Any]:
    """Muffy drafts an edit: validates it, produces a sample output from the
    CURRENT version, and opens an approval. Nothing is published here."""
    _need(principal, "skill.write")
    current = active_version(session, principal.organization_id, slug)
    if current is None:
        raise KeyError(f"skill '{slug}' not published")
    from .skills_lib import _parse_frontmatter, hash_bytes

    meta, _ = _parse_frontmatter(new_body)
    if meta["name"] != slug or meta["version"] != new_version:
        raise SkillError("skill name and version must match the proposal")
    if tuple(map(int, new_version.split("."))) <= tuple(map(int, current.version.split("."))):
        raise SkillError("new skill version must be greater than the active version")
    sd = SkillDef(slug=slug, name=meta["name"], version=new_version,
                  description=meta.get("description", ""), body=new_body,
                  schema_input=current.schema_input, schema_output=current.schema_output,
                  content_hash=hash_bytes(new_body.encode()))
    sample_input = {"business_name": "Sample Business", "website": "https://example.com"} \
        if "business_name" in (current.schema_input.get("properties") or {}) else {}
    sample: Dict[str, Any] = {"note": "no sample input available"}
    candidate_sample: Dict[str, Any] = {"note": "no sample input available"}
    if sample_input:
        provider = providers.DevProvider()
        out, _ver = run_skill(session, principal.organization_id, slug, sample_input,
                              {"provider": provider, "fetch": _sample_fetch(provider)})
        sample = out
        candidate_sample = skill_impl(slug)(
            {"provider": provider, "fetch": _sample_fetch(provider),
             "skill_instructions": new_body, "skill_version": new_version},
            sample_input,
        )
        errors = validate(candidate_sample, current.schema_output, "output")
        if errors:
            raise SkillError("candidate sample failed schema: " + "; ".join(errors))
    ap = create_approval(session, principal.organization_id, "skill.publish",
                         {"slug": slug, "version": new_version, "body": new_body,
                          "reason": reason, "schema_input": current.schema_input,
                          "schema_output": current.schema_output},
                         requested_by=principal.display or principal.id)
    audit.log(session, principal, "skill.propose_edit", "skill", slug,
              {"version": new_version, "approval_id": ap.id})
    return {"approval_id": ap.id, "slug": slug, "proposed_version": new_version,
            "current_version": current.version, "sample_output": sample,
            "proposed_sample_output": candidate_sample}


def execute_skill_publish(session: Session, principal: Principal, payload: Dict[str, Any],
                          approval_id: str) -> Any:
    """Runs ONLY from the approvals flow, after an owner approved skill.publish."""
    _need(principal, "skill.publish")
    sd = SkillDef(slug=payload["slug"], name=payload["slug"], version=payload["version"],
                  description="", body=payload["body"],
                  schema_input=payload.get("schema_input") or {},
                  schema_output=payload.get("schema_output") or {})
    import hashlib
    sd.content_hash = hashlib.sha256(sd.body.encode()).hexdigest()
    sv = publish(session, principal.organization_id, sd,
                 created_by=principal.display or principal.id, approval_id=approval_id)
    audit.log(session, principal, "skill.publish", "skill", payload["slug"],
              {"version": payload["version"], "approval_id": approval_id})
    return sv


def request_skill_rollback(session: Session, principal: Principal, slug: str,
                           to_version: str) -> Dict[str, Any]:
    _need(principal, "skill.rollback")
    if active_version(session, principal.organization_id, slug) is None:
        raise KeyError(f"skill '{slug}' not published")
    ap = create_approval(session, principal.organization_id, "skill.rollback",
                         {"slug": slug, "to_version": to_version},
                         requested_by=principal.display or principal.id)
    audit.log(session, principal, "skill.request_rollback", "skill", slug,
              {"to_version": to_version, "approval_id": ap.id})
    return {"approval_id": ap.id, "slug": slug, "to_version": to_version}


def execute_skill_rollback(session: Session, principal: Principal, payload: Dict[str, Any],
                           approval_id: str) -> Any:
    _need(principal, "skill.rollback")
    sv = rollback(session, principal.organization_id, payload["slug"], payload["to_version"])
    audit.log(session, principal, "skill.rollback", "skill", payload["slug"],
              {"to_version": payload["to_version"], "approval_id": approval_id})
    return sv


# --------------------------------------------------------------- schedules --
def manage_schedule(session: Session, principal: Principal, action: str,
                    name: Optional[str] = None, interval_seconds: int = 3600,
                    agent_slug: Optional[str] = None, input_data: Optional[Dict[str, Any]] = None,
                    schedule_id: Optional[str] = None) -> Dict[str, Any]:
    _need(principal, "schedule.manage")
    if action == "create":
        if not (name and agent_slug):
            raise SkillError("schedule create needs name and agent_slug")
        agent = (session.query(Agent)
                 .filter_by(organization_id=principal.organization_id, slug=agent_slug,
                            status="active").one_or_none())
        if agent is None:
            raise KeyError(f"unknown agent '{agent_slug}'")
        import datetime
        s = Schedule(organization_id=principal.organization_id, name=name,
                     interval_seconds=interval_seconds, agent_slug=agent_slug,
                     skill_slug=agent.skills[0] if agent.skills else None,
                     input=input_data or {},
                     next_run_at=utcnow() + datetime.timedelta(seconds=interval_seconds))
        session.add(s)
        session.commit()
        session.refresh(s)
        audit.log(session, principal, "schedule.create", "schedule", s.id, {"name": name})
        return {"id": s.id, "name": s.name, "status": s.status, "next_run_at": str(s.next_run_at)}
    if action in ("pause", "resume"):
        s = (session.query(Schedule)
             .filter_by(id=schedule_id, organization_id=principal.organization_id).one_or_none())
        if s is None:
            raise KeyError("schedule not found")
        s.status = "paused" if action == "pause" else "active"
        session.commit()
        audit.log(session, principal, f"schedule.{action}", "schedule", s.id, {})
        return {"id": s.id, "status": s.status}
    if action == "list":
        rows = (session.query(Schedule)
                .filter_by(organization_id=principal.organization_id).all())
        return {"schedules": [{"id": s.id, "name": s.name, "agent": s.agent_slug,
                               "interval_seconds": s.interval_seconds, "status": s.status,
                               "next_run_at": str(s.next_run_at)} for s in rows]}
    raise SkillError(f"unknown schedule action '{action}'")


# -------------------------------------------------------------------- cost --
def cost_report(session: Session, principal: Principal) -> Dict[str, Any]:
    _need(principal, "cost.read")
    from sqlalchemy import func

    from .models import UsageCost
    rows = (session.query(UsageCost.provider, UsageCost.model,
                          func.count(UsageCost.id), func.sum(UsageCost.tokens_in),
                          func.sum(UsageCost.tokens_out), func.sum(UsageCost.cost_usd))
            .filter_by(organization_id=principal.organization_id)
            .group_by(UsageCost.provider, UsageCost.model).all())
    items = [{"provider": p, "model": m, "calls": c, "tokens_in": ti or 0,
              "tokens_out": to or 0, "cost_usd": round(usd or 0.0, 6)}
             for p, m, c, ti, to, usd in rows]
    return {"total_usd": round(sum(i["cost_usd"] for i in items), 6), "by_model": items}


# --------------------------------------------------------- approval router --
def execute_approved(session: Session, principal: Principal, approval: Any) -> Any:
    """Dispatch an approved action. Only called after approval status=approved."""
    if approval.action == "skill.publish":
        return execute_skill_publish(session, principal, approval.payload, approval.id)
    if approval.action == "skill.rollback":
        return execute_skill_rollback(session, principal, approval.payload, approval.id)
    raise SkillError(f"no executor for approved action '{approval.action}'")
