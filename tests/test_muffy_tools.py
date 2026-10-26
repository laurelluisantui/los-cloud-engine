"""Exercise the actual Agents SDK tool wrappers without making a model call."""
import asyncio
import json
import sys

import pytest

from engine.auth import Principal, get_org_id
from engine.db import SessionLocal
from engine.muffy import _build_tools


@pytest.mark.skipif(sys.version_info < (3, 10),
                    reason="Agents SDK requires Python 3.10+; CI/Docker uses 3.12")
def test_sdk_tools_delegate_and_report_real_status(seeded):
    session = SessionLocal()
    owner = Principal(kind="owner", id="owner-user-1", organization_id=get_org_id(session))
    tools = {t.name: t for t in _build_tools(session, owner, "chat-1")}
    assert "tool_delegate_task" in tools

    async def invoke(name, **kwargs):
        return json.loads(await tools[name].on_invoke_tool(None, json.dumps(kwargs)))

    task = asyncio.run(invoke(
        "tool_delegate_task", agent_slug="sales-research",
        input_json=json.dumps({"business_name": "Acme", "website": "https://acme.example"}),
        skill_slug="prospect-research",
    ))
    assert task["status"] == "queued"
    status = asyncio.run(invoke("tool_task_status", task_id=task["task_id"]))
    assert status["status"] == "queued"
    assert status["runs"] == []  # no fabricated execution
    session.close()
