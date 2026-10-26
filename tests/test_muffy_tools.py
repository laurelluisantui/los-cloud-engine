"""Exercise the actual Agents SDK tool wrappers without making a model call."""
import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from engine import config
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


@pytest.mark.skipif(sys.version_info < (3, 10),
                    reason="Agents SDK requires Python 3.10+; CI/Docker uses 3.12")
def test_chat_stream_saves_actual_sdk_result(client, owner_headers, seeded, monkeypatch):
    import agents

    class FakeStream:
        context_wrapper = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=20, output_tokens=10)
        )

        async def stream_events(self):
            yield SimpleNamespace(type="raw_response_event",
                                  data=SimpleNamespace(delta="Task is queued."))

    monkeypatch.setattr(config, "OPENAI_API_KEY", "test-only-placeholder")
    monkeypatch.setattr(agents.Runner, "run_streamed",
                        staticmethod(lambda agent, history: FakeStream()))
    r = client.post("/v1/chat", headers=owner_headers, json={"message": "Check my task"})
    assert r.status_code == 200, r.text
    events = [json.loads(line[6:]) for line in r.text.splitlines()
              if line.startswith("data: ")]
    assert events[0] == {"type": "token", "data": "Task is queued."}
    assert events[-1]["type"] == "done"
    conv_id = events[-1]["data"]["conversation_id"]
    saved = client.get(f"/v1/conversations/{conv_id}/messages",
                       headers=owner_headers).json()["messages"]
    assert [m["content"] for m in saved] == ["Check my task", "Task is queued."]
    costs = client.get("/v1/costs", headers=owner_headers).json()
    assert costs["by_model"][0]["tokens_in"] == 20
    assert costs["by_model"][0]["tokens_out"] == 10
