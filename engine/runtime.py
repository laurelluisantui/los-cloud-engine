"""Task execution runtime. Loads the agent's allowed skill from the registry
and runs it with injected, least-privilege context (model provider + bounded
HTTP fetch). Records real usage/cost; errors propagate to the worker."""
import re
import threading
from typing import Any, Dict, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from . import providers
from .models import Agent, Task, TaskRun, UsageCost, utcnow
from .skills_lib import run_skill

_MAX_BYTES = 512 * 1024
_BLOCKLIST = re.compile(r"^(localhost|127\.|0\.0\.0\.0|169\.254\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)")


def bounded_fetch(url: str, timeout: float = 15.0) -> str:
    """Least-privilege fetch: http(s) only, no private/link-local hosts, size-capped."""
    host = urlparse(url).hostname or ""
    if _BLOCKLIST.match(host):
        raise ValueError(f"refused to fetch private host: {host}")
    with httpx.Client(timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "LOS-CloudEngine/0.1"}) as client:
        with client.stream("GET", url) as r:
            r.raise_for_status()
            chunks = []
            total = 0
            for chunk in r.iter_bytes(8192):
                total += len(chunk)
                if total > _MAX_BYTES:
                    break
                chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def execute_task(session: Session, task: Task, fetch: Any = None) -> Tuple[Dict[str, Any], TaskRun]:
    agent = session.query(Agent).filter_by(id=task.agent_id).one()

    provider = providers.get_provider()
    context: Dict[str, Any] = {
        "provider": provider,
        "fetch": fetch or bounded_fetch,
        "organization_id": task.organization_id,
        "agent_permissions": agent.permissions,
        "stop_event": threading.Event(),
    }
    run = TaskRun(organization_id=task.organization_id, task_id=task.id,
                  attempt=max(task.attempts, 1), status="running")
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        output, version = run_skill(session, task.organization_id,
                                    task.skill_slug or agent.skills[0],
                                    task.input, context)
        run.status = "succeeded"
        run.skill_version = version
        run.output = output
    finally:
        usage = context.get("usage")  # skills report provider usage here when available
        if usage:
            run.tokens_in = usage.get("tokens_in", 0)
            run.tokens_out = usage.get("tokens_out", 0)
            run.cost_usd = usage.get("cost_usd", 0.0)
            session.add(UsageCost(organization_id=task.organization_id, task_run_id=run.id,
                                  provider=usage.get("provider", "dev"),
                                  model=usage.get("model", ""),
                                  tokens_in=run.tokens_in, tokens_out=run.tokens_out,
                                  cost_usd=run.cost_usd))
        run.finished_at = utcnow()
        session.commit()
        session.refresh(run)
    return run.output, run
