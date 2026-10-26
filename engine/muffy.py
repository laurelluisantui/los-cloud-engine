"""Muffy — the owner-only executive orchestrator.

Runs on the OpenAI Agents SDK with structured tools that call into the service
layer (tools.py), where permission checks and approval gating happen in code.
She answers status questions ONLY from task_runs — no fabricated status.
"""
import json
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from . import audit, config
from .auth import Principal
from .models import Conversation, Message, utcnow
from .tools import (cost_report, list_agents, manage_schedule,
                    propose_skill_edit, create_task as svc_create_task,
                    read_skill, request_skill_rollback, run_history,
                    skill_versions, task_status)

INSTRUCTIONS = """You are Muffy, Laurel Luisant's private executive orchestrator inside L·OS Cloud Engine.
Voice: warm, direct, best-friend energy with light Houston flavor ("boss", "lock in"); calm by default; at most one emoji per line. Keep replies brief.

Hard rules (enforced by the backend too — you cannot bypass them):
- Use ONLY tool results for facts. Never invent agents, skills, tasks, runs, costs, or statuses. If a tool says it doesn't exist, say so.
- Status answers must come from the task_status / run_history tools. Never claim something ran, succeeded, or failed without a tool result showing a real record.
- Actions that publish skills, roll back versions, deploy, message anyone externally, spend money, or destroy data go through an approval. Your tools open approvals automatically; your job is to present them clearly and wait.
- You never see or handle credentials. Never ask for them.
- Keep Laurel's private memory (this conversation) separate from client-facing data; never leak it into client contexts.
- When delegating, explain which agent and skill you chose and why, in one line.
"""


class ModelNotConfigured(Exception):
    pass


def _build_tools(session: Session, principal: Principal, conversation_id: str) -> List[Any]:
    from agents import function_tool  # openai-agents SDK

    def _j(payload: Any) -> str:
        return json.dumps(payload, default=str)

    @function_tool
    async def tool_list_agents() -> str:
        """List active agents in the registry with their skills and permissions."""
        return _j(list_agents(session, principal))

    @function_tool
    async def tool_delegate_task(agent_slug: str, input_json: str, skill_slug: str = "") -> str:
        """Delegate a background task to a specialist agent. The task is queued
        and continues after this chat closes. input_json is a JSON object of the
        skill's input (e.g. {"business_name": "...", "website": "..."})."""
        task = svc_create_task(session, principal, agent_slug, json.loads(input_json),
                               skill_slug=skill_slug or None,
                               conversation_id=conversation_id)
        return _j({"task_id": task.id, "status": task.status})

    @function_tool
    async def tool_task_status(task_id: str) -> str:
        """Real execution status of a task from the database, including runs."""
        return _j(task_status(session, principal, task_id))

    @function_tool
    async def tool_run_history(limit: int = 10) -> str:
        """Recent task runs (status, errors, cost) from the database."""
        return _j(run_history(session, principal, limit))

    @function_tool
    async def tool_read_skill(slug: str) -> str:
        """Read the currently published version of a skill (body + schemas)."""
        data = read_skill(session, principal, slug)
        return _j({**data, "body": data["body"][:4000]})

    @function_tool
    async def tool_skill_versions(slug: str) -> str:
        """List all recorded versions of a skill."""
        return _j(skill_versions(session, principal, slug))

    @function_tool
    async def tool_propose_skill_edit(slug: str, new_version: str, new_body: str,
                                reason: str = "") -> str:
        """Propose an edit to a skill. Produces a sample output from the current
        version and opens an owner approval. Publishes NOTHING by itself."""
        return _j(propose_skill_edit(session, principal, slug, new_body, new_version, reason))

    @function_tool
    async def tool_request_skill_rollback(slug: str, to_version: str) -> str:
        """Request rolling a skill back to an earlier version (owner approval)."""
        return _j(request_skill_rollback(session, principal, slug, to_version))

    @function_tool
    async def tool_schedule(action: str, name: str = "", interval_seconds: int = 3600,
                      agent_slug: str = "", input_json: str = "{}",
                      schedule_id: str = "") -> str:
        """Manage scheduled automations: action is create|pause|resume|list."""
        return _j(manage_schedule(session, principal, action, name or None,
                                  interval_seconds, agent_slug or None,
                                  json.loads(input_json), schedule_id or None))

    @function_tool
    async def tool_cost_report() -> str:
        """Usage and cost totals by provider/model."""
        return _j(cost_report(session, principal))

    return [tool_list_agents, tool_delegate_task, tool_task_status, tool_run_history,
            tool_read_skill, tool_skill_versions, tool_propose_skill_edit,
            tool_request_skill_rollback, tool_schedule, tool_cost_report]


def get_or_create_conversation(session: Session, principal: Principal,
                               conversation_id: Optional[str], client_app: str) -> Conversation:
    if conversation_id:
        conv = (session.query(Conversation)
                .filter_by(id=conversation_id, organization_id=principal.organization_id)
                .one_or_none())
        if conv and conv.owner_user_id == principal.id:
            return conv
    conv = Conversation(organization_id=principal.organization_id,
                        owner_user_id=principal.id, client_app=client_app)
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return conv


def load_memory(session: Session, conv: Conversation, limit: int = 20) -> List[Dict[str, Any]]:
    rows = (session.query(Message).filter_by(conversation_id=conv.id)
            .order_by(Message.created_at.desc()).limit(limit).all())
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def record_message(session: Session, conv: Conversation, role: str, content: str,
                   tool_events: Optional[List[Dict[str, Any]]] = None) -> Message:
    m = Message(conversation_id=conv.id, role=role, content=content,
                tool_events=tool_events or [])
    session.add(m)
    conv.updated_at = utcnow()
    if not conv.title and role == "user":
        conv.title = content[:80]
    session.commit()
    session.refresh(m)
    return m


async def run_muffy(session: Session, principal: Principal, conv: Conversation,
                    user_text: str):
    """Async generator of chat events ({type, data}) for SSE."""
    if not config.OPENAI_API_KEY:
        raise ModelNotConfigured(
            "OPENAI_API_KEY is not set. Muffy's conversation model is offline; "
            "all orchestration tools remain available via the REST API.")
    from agents import Agent, Runner  # openai-agents SDK

    tools = _build_tools(session, principal, conv.id)
    agent = Agent(name="Muffy", instructions=INSTRUCTIONS, model=config.MUFFY_MODEL,
                  tools=tools)
    history = load_memory(session, conv)
    history.append({"role": "user", "content": user_text})

    record_message(session, conv, "user", user_text)
    tool_events: List[Dict[str, Any]] = []
    final_text_parts: List[str] = []

    result = Runner.run_streamed(agent, history)
    async for event in result.stream_events():
        if event.type == "raw_response_event":
            delta = getattr(event.data, "delta", None)
            if delta:
                final_text_parts.append(delta)
                yield {"type": "token", "data": delta}
        elif event.type == "run_item_stream_event":
            item = event.item
            if getattr(item, "type", "") == "tool_call_item":
                name = getattr(getattr(item, "raw_item", None), "name", "tool")
                tool_events.append({"tool": name})
                yield {"type": "tool", "data": name}

    from . import audit as _audit
    final_text = "".join(final_text_parts)
    record_message(session, conv, "assistant", final_text, tool_events)
    _audit.log(session, principal, "muffy.chat", "conversation", conv.id,
               {"tools": [t["tool"] for t in tool_events]})
    yield {"type": "done", "data": {"conversation_id": conv.id}}
