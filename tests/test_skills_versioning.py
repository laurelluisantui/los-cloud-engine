"""Skills Library: versioned publish via approval, sample outputs, rollback."""
import os

import engine.config as config
from engine.db import SessionLocal


NEW_BODY = """---
name: prospect-research
version: 0.2.0
description: Improved research brief with stricter note discipline.
---

# prospect-research

Everything from 0.1.0, plus: notes must name the page checked and the missing fact.
"""


def _isolated_skills_dir(tmp_path, monkeypatch):
    """The dir is isolated for every test by the autouse conftest fixture;
    this just returns the active (tmp) skills directory."""
    return config.SKILLS_DIR


def test_propose_approve_publish_flow(client, owner_headers, seeded):
    r = client.get("/v1/skills/prospect-research", headers=owner_headers)
    assert r.status_code == 200
    assert r.json()["version"] == "0.1.0"

    r = client.post("/v1/skills/prospect-research/propose", headers=owner_headers,
                    json={"new_version": "0.2.0", "body": NEW_BODY,
                          "reason": "stricter notes"})
    assert r.status_code == 202, r.text
    payload = r.json()
    assert payload["current_version"] == "0.1.0"
    assert payload["proposed_version"] == "0.2.0"
    approval_id = payload["approval_id"]
    # sample output from the CURRENT version accompanies the proposal
    assert "findings" in payload["sample_output"]

    # still 0.1.0 until the owner approves
    assert client.get("/v1/skills/prospect-research",
                      headers=owner_headers).json()["version"] == "0.1.0"
    pending = client.get("/v1/approvals", headers=owner_headers).json()["approvals"]
    assert any(a["id"] == approval_id and a["action"] == "skill.publish" for a in pending)

    r = client.post(f"/v1/approvals/{approval_id}/decide", headers=owner_headers,
                    json={"approve": True})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["published"]["version"] == "0.2.0"
    now = client.get("/v1/skills/prospect-research", headers=owner_headers).json()
    assert now["version"] == "0.2.0"
    assert "stricter note discipline" in now["body"]

    versions = client.get("/v1/skills/prospect-research/versions",
                          headers=owner_headers).json()["versions"]
    assert {v["version"] for v in versions} == {"0.1.0", "0.2.0"}


def test_publish_written_to_disk_exact_bytes(client, owner_headers, seeded,
                                             tmp_path, monkeypatch):
    dst = _isolated_skills_dir(tmp_path, monkeypatch)
    r = client.post("/v1/skills/prospect-research/propose", headers=owner_headers,
                    json={"new_version": "0.2.0", "body": NEW_BODY, "reason": ""})
    approval_id = r.json()["approval_id"]
    client.post(f"/v1/approvals/{approval_id}/decide", headers=owner_headers,
                json={"approve": True})
    on_disk = open(os.path.join(dst, "prospect-research", "SKILL.md")).read()
    assert on_disk == NEW_BODY


def test_reject_keeps_current_version(client, owner_headers, seeded):
    r = client.post("/v1/skills/prospect-research/propose", headers=owner_headers,
                    json={"new_version": "0.2.0", "body": NEW_BODY, "reason": ""})
    approval_id = r.json()["approval_id"]
    client.post(f"/v1/approvals/{approval_id}/decide", headers=owner_headers,
                json={"approve": False})
    assert client.get("/v1/skills/prospect-research",
                      headers=owner_headers).json()["version"] == "0.1.0"


def test_rollback_requires_approval_and_restores(client, owner_headers, seeded,
                                                 tmp_path, monkeypatch):
    _isolated_skills_dir(tmp_path, monkeypatch)
    r = client.post("/v1/skills/prospect-research/propose", headers=owner_headers,
                    json={"new_version": "0.2.0", "body": NEW_BODY, "reason": ""})
    client.post(f"/v1/approvals/{r.json()['approval_id']}/decide",
                headers=owner_headers, json={"approve": True})

    r = client.post("/v1/skills/prospect-research/rollback", headers=owner_headers,
                    json={"to_version": "0.1.0"})
    assert r.status_code == 202
    rollback_approval = r.json()["approval_id"]
    # not rolled back yet
    assert client.get("/v1/skills/prospect-research",
                      headers=owner_headers).json()["version"] == "0.2.0"
    client.post(f"/v1/approvals/{rollback_approval}/decide", headers=owner_headers,
                json={"approve": True})
    assert client.get("/v1/skills/prospect-research",
                      headers=owner_headers).json()["version"] == "0.1.0"


def test_double_decide_conflict(client, owner_headers, seeded):
    r = client.post("/v1/skills/prospect-research/propose", headers=owner_headers,
                    json={"new_version": "0.2.0", "body": NEW_BODY, "reason": ""})
    approval_id = r.json()["approval_id"]
    assert client.post(f"/v1/approvals/{approval_id}/decide", headers=owner_headers,
                       json={"approve": True}).status_code == 200
    assert client.post(f"/v1/approvals/{approval_id}/decide", headers=owner_headers,
                       json={"approve": True}).status_code == 409


def test_version_conflict_same_number_different_content(client, owner_headers, seeded):
    from engine.skills_lib import SkillError, load_skill_dir, publish
    from engine.auth import get_org_id
    session = SessionLocal()
    sd = load_skill_dir("prospect-research")
    sd.body = sd.body + "\nTampered.\n"
    import hashlib
    sd.content_hash = hashlib.sha256(sd.body.encode()).hexdigest()
    try:
        publish(session, get_org_id(session), sd, created_by="test", write_files=False)
        assert False, "expected SkillError for same-version different-content"
    except SkillError:
        pass
    session.close()
