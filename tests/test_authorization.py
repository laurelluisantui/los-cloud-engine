"""Authorization: enforced in backend code, not in prompts."""

import engine.auth as auth


def test_no_credentials_rejected(client, seeded):
    assert client.get("/v1/agents").status_code == 401
    assert client.post("/v1/tasks", json={"agent_slug": "sales-research"}).status_code == 401
    assert client.post("/v1/chat", json={"message": "hi"}).status_code == 401


def test_invalid_engine_key_rejected(client, seeded):
    r = client.get("/v1/agents", headers={"X-Engine-Key": "losk_wrong"})
    assert r.status_code == 401


def test_non_owner_supabase_token_rejected(client, seeded, monkeypatch):
    def deny(token):
        from fastapi import HTTPException
        raise HTTPException(403, "Muffy is owner-only")
    monkeypatch.setattr(auth, "verify_supabase_token", deny)
    r = client.post("/v1/chat", headers={"Authorization": "Bearer client-token"},
                    json={"message": "hi"})
    assert r.status_code == 403


def test_owner_jwt_accepted(client, seeded, owner_headers):
    r = client.get("/v1/agents", headers=owner_headers)
    assert r.status_code == 200
    slugs = [a["slug"] for a in r.json()["agents"]]
    assert "sales-research" in slugs and "muffy" in slugs


def test_machine_key_scope_enforcement(client, machine_headers, owner_headers):
    # machine key has task.create but NOT skill.publish / approval.decide
    r = client.get("/v1/agents", headers=machine_headers)
    assert r.status_code == 200
    r = client.post("/v1/chat", headers=machine_headers, json={"message": "hi"})
    assert r.status_code == 403  # chat is owner-only
    r = client.post("/v1/approvals/whatever/decide", headers=machine_headers,
                    json={"approve": True})
    assert r.status_code == 403  # machines never decide approvals
    # machine key cannot mint new keys
    r = client.post("/v1/keys", headers=machine_headers,
                    json={"name": "x", "scopes": ["task.read"]})
    assert r.status_code == 403


def test_machine_key_without_task_scope_cannot_create(client, session, seeded, monkeypatch):
    from engine.auth import get_org_id, hash_key
    from engine.models import ApiKey
    raw = "losk_readonly"
    session.add(ApiKey(organization_id=get_org_id(session), name="ro",
                       key_hash=hash_key(raw), scopes=["task.read"]))
    session.commit()
    monkeypatch.setattr(auth, "verify_supabase_token", lambda t: {"id": "u"})
    r = client.post("/v1/tasks", headers={"X-Engine-Key": raw},
                    json={"agent_slug": "sales-research", "input": {}})
    assert r.status_code == 403


def test_key_mint_blocks_approval_escalation(client, owner_headers):
    r = client.post("/v1/keys", headers=owner_headers,
                    json={"name": "bad", "scopes": ["approval.decide"]})
    assert r.status_code == 400


def test_machine_cannot_fire_events_or_read_approvals(client, machine_headers):
    assert client.post("/v1/events/new-lead", headers=machine_headers,
                       json={}).status_code == 403
    assert client.get("/v1/approvals", headers=machine_headers).status_code == 403
