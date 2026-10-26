from pathlib import Path

from engine.auth import get_org_id, hash_key
from engine.db import SessionLocal
from engine.models import Agent, ApiKey, Organization


def test_other_organization_cannot_read_owner_agents_or_tasks(
    client, owner_headers, seeded
):
    r = client.post("/v1/tasks", headers=owner_headers, json={
        "agent_slug": "sales-research",
        "input": {"business_name": "Acme", "website": "https://acme.example"}
    })
    task_id = r.json()["task_id"]
    s = SessionLocal()
    other = Organization(slug="client-tenant", name="Other")
    s.add(other)
    s.commit()
    s.add(ApiKey(organization_id=other.id, name="other",
                 key_hash=hash_key("losk_other"), scopes=["agent.read", "task.read"]))
    s.commit()
    s.close()
    headers = {"X-Engine-Key": "losk_other"}
    assert client.get("/v1/agents", headers=headers).json()["agents"] == []
    assert client.get(f"/v1/tasks/{task_id}", headers=headers).status_code == 404


def test_rls_policies_have_no_missing_context_fallback():
    sql = (Path(__file__).resolve().parents[1] /
           "db/migrations/0002_rls.sql").read_text()
    assert "coalesce" not in sql.lower()
    assert "WITH CHECK" in sql
    assert "app.organization_id" in sql
    assert "app.user_id" in sql
    assert "app.api_key_hash" in sql


def test_failed_approved_action_is_recorded_once(client, owner_headers, seeded):
    from engine.models import Approval

    s = SessionLocal()
    s.add(Approval(organization_id=get_org_id(s), action="skill.rollback",
                   payload={"slug": "missing-skill", "to_version": "0.0.0"},
                   requested_by="test"))
    s.commit()
    approval_id = s.query(Approval).one().id
    s.close()
    url = f"/v1/approvals/{approval_id}/decide"
    assert client.post(url, headers=owner_headers, json={"approve": True}).status_code == 500
    s = SessionLocal()
    assert s.query(Approval).filter_by(id=approval_id).one().status == "failed"
    s.close()
    assert client.post(url, headers=owner_headers, json={"approve": True}).status_code == 409
