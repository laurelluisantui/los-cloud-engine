"""Muffy chat API: owner-only, streams cleanly, and — without a model key —
says the model is offline instead of fabricating an answer or status."""
import json


def _sse_events(text):
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


def test_chat_requires_owner(client, machine_headers, seeded):
    r = client.post("/v1/chat", headers=machine_headers, json={"message": "hi"})
    assert r.status_code == 403


def test_chat_without_model_key_reports_offline(client, owner_headers, seeded):
    r = client.post("/v1/chat", headers=owner_headers,
                    json={"message": "What ran today?"})
    assert r.status_code == 200  # SSE stream
    events = _sse_events(r.text)
    assert events, "expected at least one SSE event"
    assert events[0]["type"] == "error"
    assert "OPENAI_API_KEY" in events[0]["data"]
    # No assistant reply is recorded when the model is offline.
    r2 = client.post("/v1/chat", headers=owner_headers,
                     json={"message": "again"})
    assert r2.status_code == 200


def test_conversation_memory_persists_owner_only(client, owner_headers,
                                                 machine_headers, seeded):
    # record a user message via the memory path without a model
    from engine.db import SessionLocal
    from engine.muffy import get_or_create_conversation, record_message
    from engine.auth import Principal, get_org_id

    session = SessionLocal()
    p = Principal(kind="owner", id="owner-user-1", organization_id=get_org_id(session),
                  permissions=[])
    conv = get_or_create_conversation(session, p, None, "laurel-haven")
    conv_id = conv.id
    record_message(session, conv, "user", "remember this is private")
    session.close()

    r = client.get(f"/v1/conversations/{conv_id}/messages", headers=owner_headers)
    assert r.status_code == 200
    assert any(m["content"] == "remember this is private" for m in r.json()["messages"])

    # machine callers can never read Muffy's memory
    r = client.get(f"/v1/conversations/{conv_id}/messages", headers=machine_headers)
    assert r.status_code == 403
