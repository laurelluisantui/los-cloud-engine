"""Task execution runtime. Loads the agent's allowed skill from the registry
and runs it with injected, least-privilege context (model provider + bounded
HTTP fetch). Records real usage/cost; errors propagate to the worker."""
import ipaddress
import socket
import threading
from typing import Any, Dict, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.orm import Session

from . import providers
from .models import Agent, Task, TaskRun, UsageCost, utcnow
from .skills_lib import run_skill

_MAX_BYTES = 512 * 1024
def _check_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("only public http(s) URLs are permitted")
    if parsed.username or parsed.password:
        raise ValueError("embedded URL credentials are not permitted")
    if parsed.port not in (None, 80, 443):
        raise ValueError("nonstandard website ports are not permitted")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or
                                        (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError("website address could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("refused private or non-public website address")


def bounded_fetch(url: str, timeout: float = 15.0) -> str:
    """Public pages only. Resolve each redirect; reject oversized responses."""
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False,
                      headers={"User-Agent": "LOS-CloudEngine/0.1"}) as client:
        for _ in range(5):
            _check_public_url(url)
            with client.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308):
                    target = r.headers.get("location")
                    if not target:
                        raise ValueError("redirect missing Location")
                    url = urljoin(url, target)
                    continue
                r.raise_for_status()
                chunks = []
                total = 0
                for chunk in r.iter_bytes(8192):
                    total += len(chunk)
                    if total > _MAX_BYTES:
                        raise ValueError("website response exceeded size limit")
                    chunks.append(chunk)
                return b"".join(chunks).decode("utf-8", errors="replace")
    raise ValueError("website redirected too many times")


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
    except Exception as exc:
        run.status = "failed"
        run.error = str(exc)[:2000]
        raise
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
